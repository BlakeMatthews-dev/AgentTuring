# ADR-K8S-021 — Tool Catalog: decorator-registered Python functions with multi-tenant cascade

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold agents invoke tools — discrete callable functions that perform
actions like searching a codebase, querying a database, or reading a
GitHub pull request. The MCP specification provides the wire protocol for
tool discovery (`tools/list`) and invocation (`tools/call`), but says
nothing about how tools are registered, versioned, overridden per tenant,
or access-controlled. That is the platform's responsibility.

Today, tool functions are scattered across modules with no consistent
registration. Discovery is a hand-maintained dispatch table (forget to
update it and a tool is silently missing). There is no versioning, so
tenants cannot pin a tool behavior while another tenant upgrades. There
is no multi-tenant override mechanism — a tenant that needs a customized
`search_codebase` must fork or add conditionals. Tool Policy
(ADR-K8S-019) needs a catalog to evaluate against, and issue #59
(custom strategy pluggability) needs a plugin entry point that does not
exist yet.

The Tool Catalog is the structured answer. It is the single source of
truth for what tools exist, who can use them, and what version they are.

## Decision

**Tools are Python functions registered via a decorator API in
`src/stronghold/tools/`, discovered via MCP `tools/list` with Tool
Policy filtering, versioned with semver, and extensible via Python
entry-point groups.**

### Registration

A tool is a Python function decorated with `@tool`:

```python
from stronghold.tools import tool

@tool(
    name="search_codebase",
    version="1.2.0",
    description="Full-text search across a repository's files",
    tags=["code", "search"],
)
def search_codebase(query: str, repo: str, max_results: int = 20) -> list[dict]:
    ...
```

The decorator registers the function, its metadata, and its input schema
(derived from the function signature and type hints) into an in-process
catalog singleton at import time.

### Multi-tenant cascade

When a client calls `tools/list`, the catalog resolves the effective tool
set through a three-level cascade:

1. **Built-in tools** — shipped with Stronghold, registered via the
   decorator in `src/stronghold/tools/`.
2. **Tenant overrides** — stored in Postgres alongside the tenant record,
   loaded at tenant initialization. Same tool name, different implementation.
3. **User overrides** — stored in the user's session configuration,
   applied on top of tenant overrides.

The cascade is applied at query time, not at registration time. The
built-in catalog always holds the full set; overrides are layered on top
when a specific tenant or user context is known.

### Discovery and access control

MCP `tools/list` returns the effective tool set for the calling user
after the cascade resolves implementations and Tool Policy (ADR-K8S-019)
filters out tools the user's role does not permit. A user who lacks the
`tool:invoke:search_codebase` permission never sees `search_codebase`
in the response.

### Versioning

Every tool entry carries a semver version string. The catalog enforces
that a tool name + version pair is unique. Tenants may pin a specific
version of a built-in tool; when no version is pinned, the latest wins.
Version bumps follow standard semver: patch for bug fixes, minor for new
optional parameters, major for breaking changes.

### No hot reload

Python's `importlib.reload()` is fragile when modules hold state, use
class registries, or participate in circular imports. Stronghold does
not attempt hot reload of tool modules. Adding or updating a built-in
tool requires a process restart — in Kubernetes, a rolling update of the
`stronghold-api` Deployment. Tenant and user overrides stored in Postgres
take effect without a restart, since they load at tenant initialization
and session start respectively.

### Customer plugin entry points

External packages register tools via a Python entry-point group:

```toml
[project.entry-points."stronghold.tools"]
my_custom_search = "my_package.tools:custom_search"
```

At startup, Stronghold discovers all packages in the `stronghold.tools`
group and registers their tools into the built-in catalog. For managed
Stronghold, customer plugins load only into tenant mission pods (P2+
from ADR-K8S-014), not the shared `stronghold-api` process, maintaining
the trust boundary from ADR-K8S-013.

### OS-level isolation

Tools that need more isolation than in-process Python (e.g., arbitrary
shell commands, untrusted code) are implemented via the Sandbox Catalog
(ADR-K8S-026). The Tool Catalog entry declares `sandbox: true` in its
metadata, and the dispatch layer routes invocations to the sandbox
infrastructure instead of calling the function in-process.

## Alternatives considered

**A) Unstructured imports — scan all modules for functions matching a
naming convention (e.g., `def tool_*`).**

- Rejected: no versioning, no access control metadata, no multi-tenant
  override, no way to distinguish a helper function from a tool.
  Discovery requires importing every module at startup and hoping nothing
  has side effects — exactly the kind of import-time surprise that causes
  hard-to-debug startup failures.

**B) YAML-only tool definitions (metadata in YAML, implementation
discovered by convention).**

- Rejected: tools ARE code. The metadata (name, version, description,
  parameter schema) belongs with the implementation, not in a separate
  file that can drift. A decorator keeps metadata and implementation in
  the same place. YAML adds a synchronization burden for no benefit.

**C) Hot-reloadable tool modules — use `importlib.reload()` to pick up
new tools without restarting.**

- Rejected: `importlib.reload()` does not re-execute `from X import Y`
  in other modules, does not update already-created class instances, and
  does not handle circular imports gracefully. In production, every
  hot-reload story eventually becomes "restart the process because reload
  missed something." Tenant/user overrides in Postgres already reload
  without a restart, covering the case where speed matters most.

**D) External tool registry service — a standalone microservice that
stores tool definitions and serves discovery requests.**

- Rejected: adds a network hop on every `tools/list` and `tools/call`.
  Tools are part of the Stronghold process; the registry hop is pure
  overhead when the tool code runs in-process anyway. The catalog is an
  in-process data structure, not a service.

## Consequences

**Positive:**

- Every tool has a single point of registration (the decorator), a
  single point of discovery (`tools/list`), and a single point of
  access control (Tool Policy evaluated against the catalog).
- Multi-tenant cascade gives tenants customization without forking the
  codebase and without affecting other tenants.
- Semver versioning lets tenants pin tool versions and upgrade on their
  own schedule.
- The entry-point mechanism gives self-hosted customers a clean plugin
  API following standard Python packaging conventions.
- The sandbox metadata flag cleanly separates in-process tools from
  those needing container isolation.

**Negative:**

- Decorator registration means tools must be importable at startup. A
  broken tool module could block the process. Mitigation: each tool
  module is imported inside a try/except, and failures are logged and
  skipped rather than crashing.
- Tenant overrides depend on Postgres being available at initialization.
  If Postgres is down, tenants get the built-in catalog only.
- No hot reload means new built-in tools require a rolling update, with
  a brief period of version skew across replicas.

**Trade-offs accepted:**

- We accept the restart requirement for built-in tools in exchange for
  reliable imports rather than fragile hot reload.
- We accept the Postgres dependency for tenant overrides in exchange for
  persistent customization that survives pod restarts.
- We accept three-level cascade complexity in exchange for clean
  multi-tenant tool customization without code forks.

## References

- Python Packaging User Guide: "Entry Points Specification"
  (https://packaging.python.org/en/latest/specifications/entry-points/)
- MCP specification: `tools/list`, `tools/call`
- Kubernetes documentation: "Deployments — Rolling Update Strategy"
- ADR-K8S-013 (hybrid execution model — trust boundary for customer code)
- ADR-K8S-014 (six-tier priority system — mission pods for customer plugins)
- ADR-K8S-019 (Tool Policy — access control evaluated against the catalog)
- ADR-K8S-026 (Sandbox Catalog — OS-level isolation for unsafe tools)
