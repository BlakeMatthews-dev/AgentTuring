# ADR-K8S-020 — Stronghold as MCP server, gateway, and orchestrator

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

MCP (Model Context Protocol) defines a standard for AI applications to
interact with external tools and data sources. The protocol specifies four
affordances: **tools** (callable functions), **prompts** (user-invokable
templates), **resources** (URI-addressable read-only data), and **sampling**
(LLM completion requests). Most MCP implementations today fall into the
"host" pattern: they consume MCP servers but do not serve MCP themselves.

Stronghold occupies a different position. It is not merely a consumer of
tools — it is a governance platform that controls which users may call
which tools, with which credentials, under which audit and security
constraints. This governance responsibility creates three distinct roles
that Stronghold must play simultaneously.

**The credential problem.** In a standard MCP deployment, the client holds
the user's credentials and passes them to MCP servers directly. Every
client must implement credential storage, rotation, and revocation
independently, and the user must trust every client with their tokens. Per
ADR-K8S-018, Stronghold holds per-user credentials in OpenBao. If external
clients call MCP servers directly, they bypass the vault entirely.

**The governance problem.** Per ADR-K8S-019, Stronghold enforces tool
policy (Casbin gates) and security scanning (Sentinel for prompt injection,
Warden for output validation) on every tool call. If external clients call
MCP servers directly, none of these gates apply.

**The composability problem.** Stronghold's agent strategies (react,
plan_execute, delegate) compose multi-tool chains where each step may call
a different tool on a different MCP server. Governance must apply at every
step, not just the first. If orchestration is outside Stronghold,
governance becomes a per-hop middleware problem with no centralized
enforcement point.

## Decision

**Stronghold serves three MCP roles from the same `stronghold-api` pod:
MCP Server, MCP Gateway, and MCP Orchestrator.** External AI clients
connect to Stronghold's MCP endpoint and never touch raw MCP guest servers
directly.

### Role 1 — MCP Server

Stronghold exposes its own tool, prompt, and resource catalogs to external
MCP clients via the standard protocol methods:

- `tools/list` — returns tools the authenticated user is permitted to see
  (filtered by the Casbin tool policy gate)
- `tools/call` — executes a tool with governance: credential injection
  from OpenBao, Sentinel input scanning, Warden output validation, policy
  evaluation, and Phoenix audit logging
- `prompts/list` and `prompts/get` — prompt templates (skills) scoped to
  the user's tenant and role
- `resources/list` and `resources/read` — URI-addressable resources
  (documentation, configuration, knowledge base) the user may access

An external client like Claude Desktop connects to Stronghold and
interacts with the full ecosystem through a single MCP connection. The
client does not need to know about the vault, the policy layer, or the
security scanners.

### Role 2 — MCP Gateway

When Stronghold proxies calls to external MCP guest servers, it injects
governance at every hop:

1. The external client calls `tools/call` on Stronghold with a tool that
   maps to an external MCP guest server.
2. Stronghold evaluates the Casbin tool policy gate.
3. If allowed, Stronghold retrieves the user's credentials from OpenBao.
4. Stronghold runs Sentinel input scanning on the tool call arguments.
5. Stronghold forwards the call to the external MCP guest server with the
   injected credentials.
6. Stronghold runs Warden output validation on the response.
7. Stronghold logs the full call to Phoenix as a structured trace.
8. Stronghold returns the governed response to the external client.

The external client never holds credentials for the target service. The
external MCP guest server never sees the client's identity — it sees
Stronghold's service identity with per-user credentials. The Phoenix
audit trail captures the complete chain.

### Role 3 — MCP Orchestrator

Stronghold's agent strategies compose multi-tool chains with governance at
every step:

- **react** — single-step tool calls in a loop. Each call passes through
  the tool policy gate, credential injection, and security scanning.
- **plan_execute** — the planner generates a sequence of steps. Before
  execution, the task-creation gate (ADR-K8S-019) evaluates the plan's
  estimated budget. During execution, each step passes through the
  per-tool-call gate independently.
- **delegate** — a parent agent delegates sub-tasks to child agents. The
  parent's task-creation gate applies to the delegation, and each child's
  tool calls pass through their own per-tool-call gates.

Governance is not a single checkpoint at the entry point — it applies at
every step. A multi-step mission that starts with a permitted tool call
cannot silently escalate to an unpermitted call in step 5.

### Transport

The MCP endpoint is served on a dedicated path (`/mcp/v1/`) alongside the
existing REST API. Clients connect via HTTP+SSE (Server-Sent Events) for
streaming, reusing the existing HTTP infrastructure (Traefik ingress, TLS
termination, OIDC authentication). For local development, a thin CLI
wrapper (`stronghold-mcp`) supports the stdio transport by connecting to
the API over HTTP internally.

### Catalog scoping

The catalogs returned by `tools/list`, `prompts/list`, and
`resources/list` are scoped by the Casbin policy layer. A user denied
access to `github.create_pr` will not see that tool listed. A tenant's
private knowledge base entries are invisible to users outside that tenant.

### Threat model inversion

The traditional MCP threat model places trust in the client: it holds
credentials, decides which servers to call, and is responsible for not
leaking secrets. Stronghold inverts this. The client holds no credentials
— it authenticates to Stronghold via OIDC and receives an access token
that grants the right to call Stronghold's MCP endpoint, nothing more.
Credentials live in the vault. Policy enforcement and security scanning
live in the gateway. This is particularly important for agentic workflows
where the "client" is an AI agent that could be a prompt-injection target.

## Alternatives considered

**A) MCP host only (consumer pattern).**

Stronghold consumes external MCP servers but does not serve MCP itself.
External AI clients connect directly to MCP servers for tool access.
This breaks the governance story entirely: Stronghold's tool policy,
credential vault, and security scanners are all bypassed. The user must
trust every client with their raw credentials, and there is no centralized
audit trail.

- Rejected: bypasses credential isolation, policy enforcement, and
  security scanning — the core value propositions of the platform.

**B) Proprietary protocol instead of MCP.**

A Stronghold-specific protocol loses interoperability with the growing MCP
client ecosystem. Claude Desktop, Cursor, Cline, Continue.dev, and other
AI tools already speak MCP. A proprietary protocol would require each
client to implement a Stronghold adapter — either Stronghold maintains
adapters for every client (unsustainable) or users cannot use their
preferred AI client.

- Rejected: loses interop with the MCP ecosystem, increases maintenance
  burden, and reduces adoption.

**C) MCP extension only (tools but not prompts or resources).**

Serve `tools/list` and `tools/call` but not prompts or resources. This
leaves Stronghold's skill catalog and knowledge base inaccessible to
external clients. Users would have to switch to Stronghold's own chat UI
for skills and resources, fragmenting the experience.

- Rejected: fragments the user experience and leaves skill and resource
  catalogs inaccessible from external clients.

**D) Separate gateway process.**

Run the MCP gateway as a separate Deployment from `stronghold-api`. This
adds operational complexity without clear benefit — the gateway uses the
same libraries, database connections, Casbin engine, OpenBao client, and
Phoenix tracing as the rest of Stronghold-API. Separating it duplicates
infrastructure for no scaling advantage, since MCP gateway traffic and
REST API traffic serve the same users.

- Rejected: duplicates infrastructure for no scaling benefit in the
  current deployment model.

## Consequences

**Positive:**

- External AI clients get governed access to the full Stronghold ecosystem
  through a single MCP connection — no per-client credential management.
- The credential vault (ADR-K8S-018) and tool policy layer (ADR-K8S-019)
  apply uniformly regardless of whether the request comes from
  Stronghold's chat UI or an external MCP client.
- Security scanning applies at every step of every multi-tool chain, not
  just at the entry point.
- The Phoenix audit trail captures the complete governance chain for every
  tool call, regardless of the originating client.
- Stronghold becomes a natural integration point for any MCP-compatible
  AI tool, broadening reach without broadening the trust surface.

**Negative:**

- Stronghold-API becomes a single point of failure for all tool access.
  Mitigated by the HA story (P0 tier, minReplicas 2, PodDisruptionBudget)
  from ADR-K8S-014.
- The MCP specification is still evolving. Breaking changes could require
  updates to the endpoint. Mitigated by versioning the path (`/mcp/v1/`)
  so a v2 can coexist.
- Serving three MCP roles from one pod increases cognitive load on
  developers. Mitigated by clean module boundaries within the codebase.

**Trade-offs accepted:**

- We accept the single-point-of-failure risk in exchange for centralized
  governance — distributed governance across every client is strictly
  worse for security and auditability.
- We accept coupling to the MCP specification's evolution in exchange for
  interoperability with the AI development tool ecosystem.
- We accept the complexity of three MCP roles in one pod in exchange for
  a unified governance enforcement point that cannot be bypassed.

## References

- MCP specification: https://modelcontextprotocol.io/specification
- MCP architecture overview: https://modelcontextprotocol.io/docs/concepts/architecture
- Kubernetes documentation: "Services, Load Balancing, and Networking"
- ADR-K8S-013 (hybrid execution model), ADR-K8S-018 (per-user credential
  vault), ADR-K8S-019 (tool policy layer)
