# ADR-K8S-023 — Resource Catalog: URI-addressable state with per-user credential injection

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Resources represent state that agents need to read but not modify — a
user's GitHub repositories, a team's on-call schedule, a tenant's
service dependency graph, a project's recent CI runs. MCP defines the
resources affordance precisely for this: URI-addressed, read-only,
discoverable, and (eventually) subscribable.

Without a catalog, agents hard-code data access patterns inside tool
implementations. A tool like `list_github_repos` fetches data AND
formats it AND handles authentication AND is the only way to access
that data. This coupling creates problems: no reuse across skills (two
skills needing the same data must call the same tool), no separation of
reading from acting (the MCP client cannot distinguish data retrieval
from side-effecting actions), no per-user credential scoping (every tool
independently handles vault lookups and token refresh), and no
addressability (a skill's data dependency is implicit in prose rather
than structural in a URI).

The Resource Catalog provides URI-addressable, read-only, per-user state
with credential injection at the resolver layer, discoverable via MCP
`resources/list` and readable via `resources/read`.

## Decision

**Resources are URI-addressable read-only state served via MCP
`resources/*`. Resolvers are Python functions registered against URI
templates. Per-call credential injection happens at the resolver layer
using the vault (ADR-K8S-018). Discovery via `resources/list` is
paginated and policy-filtered. `resources/subscribe` is deferred to
v1.x.**

### URI scheme

Resources use the `stronghold://` scheme with a three-level namespace
encoding the identity scope:

```
stronghold://global/<path>          # Platform-wide resources
stronghold://tenant/<id>/<path>     # Tenant-scoped resources
stronghold://user/<id>/<path>       # User-scoped resources
```

Examples: `stronghold://global/models` (the model registry),
`stronghold://tenant/acme/services` (Acme Corp's service catalog),
`stronghold://user/alice/github/repos` (Alice's GitHub repositories).

The URI prefix is the namespace enforcement mechanism. A request for
`stronghold://user/alice/...` from Bob is rejected by the policy layer
before the resolver is invoked. The namespace is structural, not
advisory.

### Resolvers

A resolver is a Python function registered against a URI template:

```python
from stronghold.resources import resolver

@resolver("stronghold://user/{user_id}/github/repos")
async def github_repos(user_id: str, credentials: VaultCredentials) -> list[dict]:
    token = credentials.get("github_pat")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"token {token}"},
        )
        return resp.json()
```

The resolver receives extracted URI template variables and a
`VaultCredentials` object containing credentials for the identity scope
encoded in the URI. The catalog framework handles the credential
lookup — the resolver author does not call the vault directly.

### Per-call credential injection

This is the most consequential design choice. When a client requests
`stronghold://user/alice/github/repos`, the catalog framework parses the
URI, extracts the identity scope (`user/alice`), looks up Alice's
credentials from the vault (ADR-K8S-018) for the resource type
(`github`), and injects them into the resolver. Alice's GitHub PAT is
used, not a shared service account token.

The injection is per-call, not per-process. Two concurrent requests for
Alice's and Bob's repos use their respective credentials even on the
same replica. The resolver is stateless with respect to identity. The
platform never needs a shared "god token" for external services, and
the vault audit log shows exactly whose credentials were used for each
access.

### Discovery and access control

`resources/list` returns resource URI templates available to the calling
user after two filters: namespace filtering (users see only global, their
tenant's, and their own namespaces) and policy filtering (Tool Policy
ADR-K8S-019 gates `resource-read` permissions). The response is paginated
because the resource set grows with users and tenants.

### Read path

`resources/read` takes a concrete URI, resolves it through the matching
resolver with injected credentials, and returns the result with a
`mimeType` hint. Caching is resolver-specific — some resolvers
(model registry) cache aggressively, others (GitHub repos) cache
briefly or not at all. The framework provides an optional
`@resolver(cache_ttl=300)` parameter but imposes no global policy.

### Deferred: `resources/subscribe`

MCP defines `resources/subscribe` for live updates via WebSocket or SSE.
This requires push infrastructure that is not justified until v1.x usage
patterns from `resources/read` reveal which resources benefit from it.
Clients that need fresh data call `resources/read` on each access; the
per-call credential injection means each read is independently
authenticated with no stale-session risk.

## Alternatives considered

**A) Resources inside tools — implement data retrieval as tool functions
that return data.**

- Rejected: couples data access to tool logic, prevents resource reuse
  across skills, and loses the MCP resources affordance. A skill that
  says "this skill needs the user's GitHub repos" should reference a
  resource URI, not a tool name. The policy engine must be able to
  distinguish "reading state" from "performing an action" to gate them
  differently.

**B) Static file-based resources only — represent resources as files on
disk or ConfigMap entries.**

- Rejected: cannot represent dynamic per-user state. "Alice's GitHub
  repos" is not a file — it is a live query against an external API
  with Alice's credentials. Static resources are a degenerate case of
  the resolver pattern (a resolver that reads a file), not the general
  case.

**C) Full CRUD resources — allow agents to create, update, and delete
resources, not just read them.**

- Rejected: MCP resources are read-only by specification. Write
  operations belong in tools, where they are subject to tool-invoke
  policy, audit logging, and confirmation flows. A resource that accepts
  writes is a tool pretending to be a resource; the policy engine cannot
  distinguish reads from deletes if both use the same affordance.

**D) Implement `resources/subscribe` immediately in v0.9.**

- Rejected: requires WebSocket/SSE push infrastructure (connection
  management, reconnection, backpressure) not justified until usage
  patterns reveal which resources benefit from live updates. The read
  path covers all v0.9 use cases without the operational complexity of
  persistent connections.

## Consequences

**Positive:**

- Resources are addressable by URI, making skill dependencies on data
  machine-readable and validatable at load time.
- Per-user credential injection eliminates shared service account tokens
  and gives the vault audit log per-user granularity.
- The namespace structure (global / tenant / user) provides structural
  multi-tenancy — no policy misconfiguration can leak resources across
  tenants because the prefix is enforced before the resolver runs.
- Resolvers are simple async Python functions with a clean contract:
  receive credentials, return data.
- The read-only contract keeps the resource surface small and auditable.

**Negative:**

- A third catalog (alongside tools and skills) means a third
  registration path, discovery endpoint, and test suite. The cost is
  justified by MCP's three-affordance design.
- Per-call credential lookup adds vault latency to every resource read.
  Mitigation: the vault client caches credentials with a short TTL
  (configurable, default 60 seconds).
- Deferring `resources/subscribe` means agents that want live data must
  poll via `resources/read`, which is less efficient but simpler to
  operate.

**Trade-offs accepted:**

- We accept per-call vault lookups in exchange for per-user credential
  scoping and auditability.
- We accept deferring `resources/subscribe` in exchange for shipping a
  simpler v0.9 without push infrastructure.
- We accept a third catalog in exchange for clean alignment with MCP's
  three-affordance model (tools, prompts, resources).

## References

- MCP specification: `resources/list`, `resources/read`,
  `resources/subscribe`
- RFC 3986: "Uniform Resource Identifier (URI): Generic Syntax"
- Kubernetes documentation: "ConfigMaps and Secrets"
- ADR-K8S-018 (per-user credential vault — credential injection source)
- ADR-K8S-019 (Tool Policy — resource-read policy gate)
- ADR-K8S-021 (Tool Catalog — resources are distinct from tools)
- ADR-K8S-022 (Skill Catalog — skills reference resources by URI)
