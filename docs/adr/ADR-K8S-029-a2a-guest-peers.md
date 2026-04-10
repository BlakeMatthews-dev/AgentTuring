# ADR-K8S-029 — A2A guest peers (outbound delegation)

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

ADR-K8S-028 establishes Stronghold as an A2A peer that receives inbound
tasks from external callers. But agent ecosystems are not one-directional.
In a realistic enterprise deployment, Stronghold's agents need to
delegate outbound — to agents on other platforms, to other Stronghold
instances in different clusters, or to customer-supplied agents running
in customer infrastructure.

Consider a concrete scenario: a tenant's Ranger agent is investigating a
security incident. It has gathered logs and identified suspicious IP
addresses, but it needs to enrich those IPs with threat intelligence from
a specialized threat-intel agent that the customer operates on a different
platform. Without outbound delegation, Ranger cannot compose with that
external agent. The operator would have to build a custom MCP tool that
wraps the external agent's API, losing the task-level semantics (progress
streaming, cancellation, structured results) that A2A provides.

The A2A specification defines how agents discover each other (via Agent
Cards) and delegate tasks (via the task lifecycle). Stronghold already
uses Agent Cards for its own catalog (ADR-K8S-027) and serves the task
lifecycle for inbound tasks (ADR-K8S-028). Outbound delegation is the
natural extension: Stronghold's agents act as A2A clients, submitting
tasks to external A2A peers and streaming their results back into the
local task context.

The multi-tenant dimension complicates outbound delegation. Each tenant
may have different external peers, different trust relationships, and
different data-sharing policies. Tenant A's agents must not be able to
delegate to tenant B's external peers unless both tenants have explicitly
agreed to that relationship. The platform must enforce tenant isolation
on outbound delegation just as it does on every other cross-tenant
boundary.

## Decision

**Stronghold's agents can delegate outbound to external A2A peers, with
per-tenant trust relationships, policy-gated authorization, and full
audit logging.**

### Peer registry

External A2A peers are registered in the `a2a_peers` Postgres table:

- `peer_id` (UUID, primary key)
- `tenant_id` (FK — which tenant owns this peer relationship)
- `name` — human-readable label for the peer
- `base_url` — the peer's A2A endpoint URL
- `agent_card_url` — the peer's Agent Card discovery URL
- `auth_method` (enum: mtls, oauth2, api_token)
- `auth_config` (JSONB — credentials reference, stored in the
  credential vault from ADR-K8S-018, never in plaintext)
- `trust_tier` (enum: T0, T1, T2, T3) — how much Stronghold trusts
  this peer's outputs
- `enabled` (boolean)
- `created_at`, `updated_at`

Peers are scoped to a tenant. Tenant A's peer registry is invisible to
tenant B. A platform-wide peer (available to all tenants) has
`tenant_id = NULL` and can only be created by an operator.

### Outbound delegation flow

When a Stronghold agent decides to delegate a sub-task to an external
peer, the following sequence executes:

1. **Agent resolution.** The agent's strategy identifies that an
   external peer is the right handler for a sub-goal. It specifies the
   target peer by name or by capability match against cached Agent
   Cards.

2. **Policy gate.** The delegation request passes through the Tool
   Policy engine (ADR-K8S-019). The policy subject is the current
   user and tenant; the object is the external peer; the action is
   `outbound_delegate`. Casbin evaluates the policy and either permits
   or denies. A denied delegation is logged and the agent falls back
   to alternative strategies.

3. **Audit emission.** Whether permitted or denied, a Phoenix span is
   emitted recording the delegation attempt, the target peer, the
   task specification, and the policy decision. This is a non-negotiable
   audit requirement for any data that leaves the Stronghold boundary.

4. **Task submission.** If permitted, Stronghold's A2A client submits a
   `tasks/create` request to the external peer's endpoint,
   authenticated using the peer's configured auth method. The task
   specification is derived from the agent's sub-goal, with tenant
   context and any sensitive data stripped per the peer's trust tier.

5. **Progress streaming.** The A2A client opens an SSE stream to the
   peer's `tasks/stream/<id>` endpoint. Progress events are forwarded
   into the parent task's event stream, so the original caller sees
   the external delegation as part of the overall task progress.

6. **Result integration.** When the external task completes, the result
   is validated against the peer's trust tier. A T3 peer's output is
   treated as untrusted and may be sandboxed or reviewed before
   integration into the parent task's result. A T0 peer's output is
   integrated directly.

### Authentication methods

Stronghold supports three authentication methods for outbound
delegation, matching the diversity of enterprise environments:

- **mTLS** — mutual TLS with client certificates. Preferred for
  peer-to-peer Stronghold communication where both sides control their
  certificate infrastructure. Certificates are stored in the credential
  vault.

- **OAuth 2.0** — client credentials grant. Used when the external peer
  requires OAuth-based authorization. Token refresh is handled
  automatically by the A2A client.

- **API token** — a static bearer token. The simplest method, used when
  the peer's API accepts token-based auth. Tokens are stored in the
  credential vault, never in the peer registry table.

### Cross-tenant delegation

Cross-tenant delegation (tenant A's agent delegating to tenant B's
external peer) is forbidden by default. Enabling it requires:

1. Both tenants must have an explicit trust relationship recorded in the
   `tenant_trust_relationships` table.
2. The trust relationship must specify which agents and which peers are
   covered.
3. The Tool Policy must have a rule permitting the cross-tenant
   delegation for the specific user, agent, and peer combination.

This three-layer gate (trust relationship + policy rule + per-call audit)
ensures that cross-tenant data flow is intentional, authorized, and
traceable.

### Data minimization

When delegating to an external peer, the agent must strip the task
specification of any data that exceeds the peer's trust tier. A T3 peer
receives only the sub-goal description and publicly available context.
A T0 peer may receive tenant-specific data if the policy permits it.
The data minimization rules are enforced by a pre-delegation filter in
the A2A client, not left to the agent strategy to implement correctly.

## Alternatives considered

**A) No outbound delegation — Stronghold agents operate only within the
Stronghold boundary.**

- Rejected: limits composability in enterprise environments where
  multiple agent platforms coexist. Customers with specialized agents
  on other platforms cannot integrate them into Stronghold workflows
  without building custom MCP tool wrappers, losing task-level
  semantics.

**B) Unrestricted delegation — any agent can delegate to any registered
peer without policy checks.**

- Rejected: violates multi-tenant isolation. Without policy gates,
  tenant A's agent could delegate to a peer that tenant B registered,
  leaking tenant A's data to tenant B's infrastructure. The policy
  gate is not optional in a multi-tenant platform.

**C) Static peer configuration in values.yaml — peers defined at deploy
time, not at runtime.**

- Rejected: does not scale for multi-tenant deployments. Each tenant
  needs its own peer relationships, which change as the tenant's
  external integrations evolve. Requiring a Helm upgrade to add a peer
  is operationally unacceptable for a platform with dozens of tenants.

**D) MCP for outbound delegation — wrap external agents as MCP tools.**

- Rejected: MCP is function-level, not task-level. Delegating a complex
  goal to an external agent requires task lifecycle semantics: progress
  streaming, cancellation, structured multi-step results. Wrapping an
  A2A peer as an MCP tool loses these semantics and forces the calling
  agent to implement its own polling and state management loop.

## Consequences

**Positive:**

- Stronghold agents can compose with external agents on any
  A2A-compatible platform, making Stronghold a natural participant in
  heterogeneous agent ecosystems.
- Per-tenant peer isolation ensures that outbound delegation respects
  multi-tenant boundaries.
- Full audit logging of every outbound delegation gives operators and
  compliance teams visibility into data that leaves the Stronghold
  boundary.
- The three authentication methods cover the range of enterprise
  integration patterns without requiring a one-size-fits-all approach.

**Negative:**

- Outbound delegation introduces a dependency on external services that
  Stronghold does not control. A misbehaving peer can stall a task,
  return garbage, or go offline. Timeout and fallback behavior must be
  robust.
- The peer registry is a new table with its own lifecycle (creation,
  credential rotation, decommissioning). Operators must manage it.
- Data minimization rules must be maintained as trust tiers evolve.
  A misconfigured filter could leak sensitive data or over-strip
  necessary context.

**Trade-offs accepted:**

- We accept the operational burden of managing external peer
  relationships in exchange for ecosystem composability.
- We accept the risk of external service dependencies in exchange for
  the ability to delegate specialized work to purpose-built agents
  outside Stronghold.
- We accept the complexity of three authentication methods in exchange
  for covering the real diversity of enterprise auth patterns.

## References

- A2A specification: agent discovery and task delegation
- OAuth 2.0 Authorization Framework: RFC 6749
- Transport Layer Security (TLS) Protocol Version 1.3: RFC 8446
- Kubernetes documentation: "Secrets" and "Network Policies"
- ADR-K8S-018 (per-user credential vault — where peer credentials live)
- ADR-K8S-019 (tool policy — policy engine for delegation authorization)
- ADR-K8S-027 (agent catalog — agent discovery via Agent Cards)
- ADR-K8S-028 (A2A peer endpoint — inbound task lifecycle)
