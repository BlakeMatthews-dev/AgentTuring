# ADR-K8S-022 — Skill Catalog: markdown teaching documents with multi-tenant cascade

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Skills are the instructional layer of Stronghold — they teach agents HOW
to accomplish goals, while tools (ADR-K8S-021) provide the ability TO do
things. A skill like "investigate a production incident" references
tools (log search, metrics query, runbook lookup) and resources (team
on-call schedule, service dependency graph) but is itself a markdown
prompt template that orchestrates their use. The distinction matters:
a tool is a callable function, a skill is a teaching document that tells
an agent which tools and resources to combine and in what order.

Without a catalog, skills are ad-hoc prompt strings embedded in
application code or scattered across configuration files. This causes
the same problems that motivated the Tool Catalog, plus a few unique to
the instructional domain:

- **No versioning.** A skill that worked yesterday may silently change
  behavior when someone edits the prompt string, with no way to track
  what changed or roll back.
- **No multi-tenancy.** A tenant that needs a customized incident
  investigation workflow (different escalation paths, different tools)
  has no clean way to override the built-in skill without forking.
- **No discovery.** External MCP clients cannot ask "what skills does
  this Stronghold instance offer?" There is no programmatic listing.
- **No separation from tools.** Without a clear boundary, skills get
  implemented as tools (Python functions that return prompt text), which
  conflates two fundamentally different primitives. Skills hot-reload
  safely because they are data (markdown text). Tools do not hot-reload
  safely because they are code (Python modules with state). Treating
  them the same forces the wrong lifecycle on one of them.

The Skill Catalog provides the structured registry that addresses all
four problems, while keeping skills cleanly separated from tools.

## Decision

**Skills are markdown documents with YAML frontmatter, stored in the
`skills/` directory and in a per-tenant Postgres table, discovered via
MCP `prompts/list`, and hot-reloadable via filesystem watcher and
database polling.**

### Format

A skill is a markdown file with YAML frontmatter:

```markdown
---
name: investigate-incident
version: "2.1.0"
description: Guide an agent through production incident investigation
tags: [ops, incident, sre]
required_tools: [search_logs, query_metrics, lookup_runbook]
required_resources: [oncall_schedule, service_dependency_graph]
allowed_tenants: ["*"]
allowed_purposes: [incident_response, postmortem]
---

# Investigate a Production Incident

You are investigating a production incident. Follow these steps:

1. **Assess severity** — query the metrics dashboard for the affected
   service using `query_metrics`. Look at error rate, latency p99, and
   availability over the last 30 minutes.

2. **Gather logs** — use `search_logs` with the service name and the
   time window from step 1. Focus on ERROR and FATAL entries.
...
```

The frontmatter declares the skill's identity, version, dependencies
(which tools and resources it requires), and access control metadata
(which tenants and purposes it applies to). The body is the actual
teaching content — markdown prose that an agent reads and follows.

### Multi-tenant cascade

Like tools, skills resolve through a three-level cascade:

1. **Built-in skills** — shipped with Stronghold in the `skills/`
   directory, version-controlled in git alongside the codebase.
2. **Tenant skills** — stored in the `tenant_skills` Postgres table.
   A tenant administrator uploads custom skills or overrides built-in
   skills (same name, different content) via the admin API.
3. **User skills** — stored in the user's session configuration. A
   user can override a skill for their own sessions.

The cascade is evaluated at query time. A `prompts/list` call returns
the effective skill set for the calling user after cascade resolution
and policy filtering.

### MCP discovery via `prompts/list`

MCP defines three affordances: tools, resources, and prompts. Skills
map to the prompts affordance because they are user-invokable templates
— a client selects a prompt (skill), the server fills in any template
variables, and the result is a structured message the agent uses as
instructions. `prompts/list` returns the skill catalog filtered by
Tool Policy (ADR-K8S-019, which gates skill-load as well as tool-invoke
permissions). `prompts/get` returns a specific skill's rendered content.

### Hot reload

Because skills are data (markdown text), not code (Python modules), they
can be safely hot-reloaded without the fragility problems that prevent
tool hot-reload:

- **Filesystem watcher** — a background thread watches the `skills/`
  directory for file changes and reloads modified skills into the
  in-memory catalog. No process restart needed.
- **Postgres polling** — a periodic task (default: every 30 seconds)
  checks the `tenant_skills` table for updated rows and refreshes the
  tenant skill cache.

Hot reload is safe here because loading a skill means reading a file and
parsing YAML frontmatter + markdown body. There is no import machinery,
no class registry, no circular dependency graph — just text parsing.

### Skills are not tools

This separation is load-bearing. Skills and tools have different:

- **Lifecycles** — skills hot-reload, tools require restart.
- **MCP affordances** — skills use `prompts/list` and `prompts/get`,
  tools use `tools/list` and `tools/call`.
- **Natures** — a skill is teaching text, a tool is executable code.
- **Authoring profiles** — a domain expert writes skills in markdown,
  a developer writes tools in Python.

A skill references tools and resources by name, creating a dependency
graph: skill "investigate-incident" requires tool "search_logs" and
resource "oncall_schedule". The catalog validates these dependencies at
load time and warns if a skill references a tool or resource that does
not exist in the catalog.

## Alternatives considered

**A) Skills as Python code — implement skills as Python functions that
return prompt text.**

- Rejected: conflates the instructional layer with the executable layer.
  A Python function cannot be safely hot-reloaded (ADR-K8S-021 explains
  why). A domain expert who understands incident investigation should
  not need to write Python to teach an agent how to investigate
  incidents. Markdown is the right format for teaching documents.

**B) Skills in the Tool Catalog — treat skills as a special type of
tool with a `type: skill` flag.**

- Rejected: tools and skills have fundamentally different lifecycles
  (hot-reload vs. restart), different MCP affordances (`prompts/*` vs.
  `tools/*`), and different authoring profiles (markdown vs. Python).
  Putting them in the same catalog means either skills inherit the
  restart requirement (wrong) or tools inherit the hot-reload fragility
  (dangerous). Separate catalogs with separate lifecycles is cleaner.

**C) No skill catalog — use ad-hoc prompt strings embedded in
application code.**

- Rejected: no versioning, no multi-tenant cascade, no discovery for
  external MCP clients, no separation of concerns between the prompt
  author and the application developer. This is the status quo and it
  does not scale.

**D) Database-only storage — store all skills in Postgres, no filesystem
representation.**

- Rejected: loses the ability to version-control skills in git alongside
  the codebase. Built-in skills should be reviewable in pull requests,
  diffable across versions, and deployable via the same CI/CD pipeline
  as the rest of the code. Tenant skills live in Postgres because they
  are tenant-specific data, but built-in skills belong in the repo.

## Consequences

**Positive:**

- Skills are discoverable via MCP `prompts/list`, giving external
  clients programmatic access to the skill catalog.
- Hot reload means a skill author can iterate on skill content without
  waiting for a full deployment cycle.
- The markdown format lowers the authoring barrier — domain experts
  write skills, developers write tools.
- Multi-tenant cascade gives tenants customization without forks.
- Dependency validation at load time catches broken skill-to-tool
  references before they cause runtime failures.

**Negative:**

- Two catalogs (tools and skills) means two registration paths, two
  discovery endpoints, and two sets of tests. The cost is justified by
  the lifecycle difference but it is still more surface area than one
  catalog.
- Filesystem watching introduces a small window where a partially
  written file could be loaded. Mitigation: the watcher debounces
  for 500ms after the last write event before loading.
- The `prompts/list` MCP affordance is a semantic stretch — MCP
  "prompts" were designed for simple templates, not multi-page teaching
  documents. This works today but may need revisiting if MCP adds a
  more specific affordance for instructional content.

**Trade-offs accepted:**

- We accept two separate catalogs in exchange for lifecycle-appropriate
  behavior (hot-reload for skills, restart for tools).
- We accept the semantic stretch of `prompts/list` in exchange for
  using a standard MCP affordance rather than inventing a custom one.
- We accept the filesystem watcher complexity in exchange for instant
  skill iteration without deployment.

## References

- MCP specification: `prompts/list`, `prompts/get`
- Kubernetes documentation: "ConfigMaps and Secrets" (analogous
  pattern for mounting data into pods)
- ADR-K8S-019 (Tool Policy — skill-load policy gate)
- ADR-K8S-021 (Tool Catalog — skills reference tools by name)
