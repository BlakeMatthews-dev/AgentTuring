# ADR-K8S-024 — MCP transport, auth, and discovery

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

MCP (Model Context Protocol) defines two transport layers: stdio for
local same-machine clients, and HTTP+SSE for remote clients. Stronghold
runs on a Kubernetes cluster, so the primary connectivity path is remote —
Claude Desktop, Cursor, and other AI-native clients connect over the
network to Stronghold's MCP endpoint. Stdio remains useful for operators
who SSH into the cluster and want to connect a local client to a running
Stronghold-API pod, but it cannot be the primary transport for external
desktop clients.

The transport question is straightforward. The harder question is
authentication and identity propagation. When a remote MCP client
connects, Stronghold must know **who the user is**, not merely that the
connection is authorized. Two critical subsystems depend on per-user
identity:

- **Vault** (ADR-K8S-018) — credentials are stored per user. A GitHub
  PAT, a Jira token, and an AWS session all belong to a specific tenant
  user. The MCP layer must propagate the authenticated user identity into
  the request context so the vault can look up the right credentials.
- **Tool Policy** (ADR-K8S-019) — which tools a user may invoke, under
  what conditions, is determined by per-user and per-tenant policy. The
  policy engine reads the user identity from the request context.

Without per-user auth, MCP access is either wide-open (anyone who can
reach the endpoint can invoke any tool with any credential) or
single-tenant-only (one shared API key, one set of credentials, one
policy). Neither is acceptable for a multi-tenant governance platform.

The MCP specification's 2025-03 revision added an authorization
framework built on OAuth 2.0 with Dynamic Client Registration (DCR).
This means MCP clients that implement the spec can negotiate an OAuth
flow automatically: the client discovers the authorization server
metadata, registers itself dynamically, obtains tokens, and presents
them on every request. This is the "golden path" for desktop AI clients
that support it.

However, not every client supports DCR today. Some clients only know how
to present a static API token. Stronghold must support both flows
during the transition period, while ensuring that both paths produce the
same result: a verified user identity in the request context.

MCP also defines capability negotiation during the `initialize`
handshake. The server declares which affordances it supports (tools,
prompts, resources, sampling). Stronghold must declare its capabilities
accurately so clients know what they can request and what they cannot.

## Decision

**Stronghold exposes MCP over HTTP+SSE as the primary remote transport,
with OAuth 2.0 + Dynamic Client Registration as the primary auth flow
and API token auth as a fallback. Stdio transport is supported for local
clients connecting via SSH tunnel. Capability negotiation declares the
affordances Stronghold supports at initialization time.**

### Transport

HTTP+SSE is the only remote transport Stronghold serves. The endpoint
lives at `/mcp/v1` on the Stronghold-API service, behind the same
Ingress and TLS termination as the rest of the API. SSE (Server-Sent
Events) handles the server-to-client streaming channel; standard HTTP
POST handles client-to-server requests. This matches the MCP
specification's Streamable HTTP transport.

Stdio transport is available for local clients. An operator who SSHs
into the cluster (or uses `kubectl exec` into a Stronghold-API pod) can
launch a stdio MCP session against the local process. This is useful for
debugging, scripting, and CI pipelines that run inside the cluster
network. Stdio sessions still require authentication — the client must
present a valid API token via an environment variable or CLI flag, which
the stdio handler validates before accepting commands.

### Authentication: OAuth 2.0 with DCR (primary)

When a remote MCP client connects, the Stronghold MCP endpoint
advertises its OAuth 2.0 authorization server metadata at the
well-known discovery URL. Clients that support DCR follow this flow:

1. The client fetches `/.well-known/oauth-authorization-server` from
   the Stronghold MCP endpoint.
2. The client dynamically registers itself at the registration endpoint
   declared in the metadata, receiving a `client_id` and
   `client_secret`.
3. The client redirects the user to the authorization endpoint for
   consent.
4. On successful consent, the client receives an access token (and
   optionally a refresh token).
5. The client presents the access token as a Bearer token on every
   subsequent MCP request.
6. Stronghold validates the token, extracts the user identity, and
   populates the request context with `tenant_id`, `user_id`, and
   `scopes`.

The authorization server is Stronghold's own OIDC layer (or a delegated
IdP like Keycloak). Dynamic client registrations are stored in Postgres
alongside the tenant's other metadata. Tokens are short-lived (15
minutes) with refresh; refresh tokens are rotated on each use.

### Authentication: API token fallback

Clients that do not support DCR can present a static API token in the
`Authorization: Bearer` header. These tokens are issued per user through
the Stronghold admin UI or API, stored hashed in Postgres, and carry the
same `tenant_id` / `user_id` / `scopes` claims as an OAuth token. The
MCP handler checks for an OAuth token first; if none is found, it falls
back to API token lookup.

API tokens have an explicit expiry (default 90 days) and can be revoked
individually. They are not a permanent backdoor — they exist to bridge
the gap until all major MCP clients support DCR.

### Identity propagation

Regardless of which auth path was used, the MCP handler populates a
`RequestContext` object with:

- `tenant_id` — the tenant the user belongs to
- `user_id` — the authenticated user
- `scopes` — the set of permissions granted (maps to tool policy roles)
- `client_id` — the MCP client that connected (useful for audit)

This context flows through every downstream call: vault credential
lookups, tool policy checks, audit event emission, quota accounting.
Every tool invocation, every model call, every audit event is tagged
with the user identity that initiated it.

### Capability negotiation

During the MCP `initialize` handshake, Stronghold declares these
capabilities:

- **tools** — supported; the server exposes tools via `tools/list` and
  executes them via `tools/call`
- **prompts** — supported; the server exposes prompt templates via
  `prompts/list` and renders them via `prompts/get`
- **resources** — supported; the server exposes resources via
  `resources/list` and reads them via `resources/read`
- **sampling** — not supported in v0.9; planned for a future release
  when Stronghold adds the ability for tools to request LLM completions
  back through the MCP channel

The declared capabilities are static per Stronghold version. They do not
vary per user or per tenant — tenant-specific restrictions are enforced
by tool policy, not by capability negotiation. A client sees all
capabilities in the handshake; policy determines what actually executes.

## Alternatives considered

**A) Stdio transport only — require clients to SSH into the cluster.**

- Rejected: desktop AI clients (Claude Desktop, Cursor, Windsurf) are
  the primary consumer of Stronghold's MCP surface. Requiring SSH tunnels
  for every desktop user is impractical at scale, breaks the experience
  for non-technical users, and means every client must maintain an SSH
  session alongside the MCP session. HTTP+SSE is the standard remote
  transport for a reason.

**B) API key only, no OAuth / DCR.**

- Rejected: API keys alone have no standard token refresh mechanism, no
  dynamic client registration, and no consent flow. Revoking access
  means rotating the key and distributing the new one manually. DCR
  gives clients a self-service registration path, short-lived tokens,
  and per-client revocation — all critical for a multi-tenant platform
  where many clients connect on behalf of many users.

**C) mTLS client certificates for authentication.**

- Rejected: mTLS provides strong machine-to-machine auth but is high
  friction for desktop AI clients. Users would need to generate, install,
  and manage client certificates. Certificate revocation (CRL or OCSP)
  adds operational complexity. No major MCP client implementation uses
  mTLS today. The MCP specification's own auth recommendation is OAuth
  2.0, not mTLS.

**D) No auth — rely on NetworkPolicy to restrict access.**

- Rejected: NetworkPolicy controls which pods can talk to which pods
  inside the cluster. It says nothing about user identity. A request
  that passes NetworkPolicy is "from an allowed network source", not
  "from user alice@tenant-foo". Without user identity, the vault cannot
  look up per-user credentials and the tool policy cannot enforce
  per-user permissions. Multi-tenant isolation collapses entirely.

## Consequences

**Positive:**

- Every MCP request carries a verified user identity, enabling per-user
  vault lookups and per-user tool policy enforcement end-to-end.
- DCR-capable clients get a zero-configuration onboarding experience:
  point the client at the Stronghold URL, authenticate once, and the
  client handles token refresh automatically.
- API token fallback ensures clients that lag behind the MCP auth spec
  can still connect without blocking adoption.
- Capability negotiation gives clients an accurate picture of what
  Stronghold supports, avoiding runtime surprises when a client tries
  to use an unsupported affordance.

**Negative:**

- Stronghold must implement or integrate an OAuth 2.0 authorization
  server with DCR support. This is a non-trivial component, though
  delegating to Keycloak covers much of the complexity.
- Two auth paths (OAuth and API token) mean two code paths to test,
  two token validation flows to secure, and two sets of documentation
  to maintain.
- Capability negotiation is static per version, which means adding a
  new capability requires a Stronghold release. This is intentional
  (capabilities should not change at runtime) but means the release
  cycle gates capability expansion.

**Trade-offs accepted:**

- We accept the complexity of supporting two auth flows (OAuth + API
  token) during the transition period in exchange for not blocking
  adoption on client-side DCR support.
- We accept the operational cost of an OAuth authorization server in
  exchange for per-user identity propagation, which is a hard
  requirement for multi-tenant vault and policy.
- We accept that sampling is deferred to a future release in exchange
  for shipping a stable tools/prompts/resources surface in v0.9.

## References

- MCP specification: "Transports" (Streamable HTTP, stdio)
- MCP specification: "Authorization" (OAuth 2.0 framework for MCP)
- OAuth 2.0 Authorization Framework, RFC 6749
- OAuth 2.0 Dynamic Client Registration Protocol, RFC 7591
- OAuth 2.0 Authorization Server Metadata, RFC 8414
- Kubernetes documentation: "Ingress" and "Services"
- ADR-K8S-018 (vault — per-user credential storage)
- ADR-K8S-019 (tool policy — per-user permission enforcement)
- ADR-K8S-002 (RBAC boundary)
