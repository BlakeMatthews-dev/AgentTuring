# ADR-K8S-027 — Agent Catalog

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold has multiple specialized agents — Artificer, Scribe, Ranger,
Warden-at-Arms, Forge — each implemented as a Python class following a
strategy pattern. These agents exist today as code scattered across the
codebase, discovered at import time, invoked by name through internal
dispatch. There is no structured registry that answers the questions an
operator, a tenant admin, or another agent needs answered before using
one: what does this agent do? What inputs does it accept? What outputs
does it produce? What trust tier does it operate at? What is its
expected cost? What SLA does it offer?

Without a catalog, agent discovery is a code-reading exercise. Adding a
new agent means writing a Python class and hoping someone updates the
docs. Multi-tenant customization — where a tenant wants to override a
built-in agent's behavior or register their own — has no structured
path. An external system that wants to delegate work to a Stronghold
agent has no machine-readable description of what that agent can do.

The A2A protocol (Google's Agent-to-Agent specification) defines the
concept of an Agent Card: a JSON document that describes an agent's
name, description, capabilities, accepted input schemas, output schemas,
authentication requirements, and operational metadata. Agent Cards are
the A2A ecosystem's discovery mechanism. Adopting Agent Cards as
Stronghold's canonical agent description format gives us a structured
registry, a machine-readable contract per agent, and interoperability
with the broader A2A ecosystem — all without inventing a custom schema.

The trust tier system from ADR-K8S-014 already assigns priority and
resource budgets to different classes of work. Agents themselves have a
trust dimension that is orthogonal to request priority: an
operator-deployed agent running at T0 is trusted differently from a
Forge-generated agent that has not yet been reviewed. The catalog must
capture this trust level per agent, so that the platform can enforce
appropriate sandboxing and audit requirements.

## Decision

**Every Stronghold agent is represented by four coordinated artifacts:
an Agent Card, a strategy implementation, a registry entry, and an A2A
endpoint.**

### Agent Card (A2A format)

Each agent has an Agent Card — a JSON document conforming to the A2A
specification's `AgentCard` schema. The card includes:

- `name` and `description` — human-readable identity
- `capabilities` — what the agent can do, expressed as A2A capability
  descriptors
- `inputSchema` and `outputSchema` — JSON Schema for the agent's
  expected task input and output
- `authentication` — what credentials the caller must present
- `metadata` — Stronghold-specific extensions including `trust_tier`
  (T0 through skull), `cost_estimate` (tokens per typical task),
  `sla` (expected completion time), `strategy_type`, and
  `tenant_scope`

Agent Cards are stored in Postgres alongside the registry entry and
served at the agent's A2A discovery endpoint (`/.well-known/agent.json`
relative to the agent's base URL).

### Strategy implementation

Each agent has a Python class implementing one of the supported strategy
patterns: `direct` (single LLM call, no tool use), `react`
(reason-act loop with tool calls), `plan_execute` (plan phase then
execute phase), `delegate` (decompose and hand off to sub-agents), or
a custom strategy registered via the strategy plugin interface. The
strategy class is the agent's runtime behavior; the Agent Card is its
external contract.

### Registry entry (Postgres)

Each agent has a row in the `agent_registry` table with:

- `agent_id` (UUID, primary key)
- `name`, `version`, `description`
- `strategy_type` (enum: direct, react, plan_execute, delegate, custom)
- `trust_tier` (enum: T0, T1, T2, T3, skull)
- `tenant_id` (nullable — NULL for built-in agents, tenant UUID for
  tenant-scoped agents, user UUID for user-scoped agents)
- `agent_card` (JSONB — the full A2A Agent Card)
- `enabled` (boolean)
- `created_at`, `updated_at`

A unique constraint on `(name, version, tenant_id)` prevents duplicate
registrations within the same scope.

### A2A endpoint

Each registered agent is reachable at an A2A endpoint that serves the
standard task lifecycle operations: `tasks/create`, `tasks/get/<id>`,
`tasks/stream/<id>`, `tasks/cancel/<id>`. The endpoint is served by
the Stronghold-API pod, which dispatches to the appropriate strategy
implementation. The Agent Card is served at the agent's discovery URL.

### Multi-tenant cascade

Agent resolution follows a three-level cascade:

1. **Built-in agents** — shipped with Stronghold, tenant_id is NULL,
   trust tier is T0 or T1. These are the default agents available to
   every tenant.
2. **Tenant agents** — registered by a tenant admin, tenant_id matches
   the requesting tenant. These can override built-in agents by name
   (the tenant's version takes precedence) or add new agents.
3. **User agents** — registered by an individual user, tenant_id is
   the user's UUID. These override tenant agents for that user only.

When Conduit resolves an agent by name, it walks the cascade from
user to tenant to built-in, returning the first match. This gives
tenants the ability to customize agent behavior without forking
Stronghold's built-in agents.

### Trust tier assignment

Trust tiers for newly registered agents are assigned by source:

- **Operator-deployed** agents (shipped with Stronghold or deployed by
  the cluster operator) start at T0 or T1.
- **Customer-supplied** agents (registered by a tenant admin via API)
  start at T2 or T3, depending on whether the tenant has an elevated
  trust agreement.
- **Forge-generated** agents (produced by the Forge builder agent) start
  at skull tier, pending promotion through the trust-tier workflow.

The trust tier determines the agent's sandboxing level, resource limits,
and audit requirements. A skull-tier agent runs in a maximally
restricted sandbox with full audit logging; a T0 agent runs with the
platform's own trust level.

### Existing agent migration

The five existing agents receive Agent Cards as part of this work:

- **Artificer** — tool-building and integration agent (T0, react strategy)
- **Scribe** — documentation and reporting agent (T0, direct strategy)
- **Ranger** — monitoring and reconnaissance agent (T0, react strategy)
- **Warden-at-Arms** — security and policy enforcement agent (T0, react
  strategy)
- **Forge** — builder agent that generates new artifacts (T0, plan_execute
  strategy; outputs start at skull tier per ADR-K8S-031)

Each gets a registry entry, an Agent Card, and an A2A endpoint.

## Alternatives considered

**A) No catalog — agents are just Python classes discovered at import
time.**

- Rejected: no structured discovery, no versioning, no multi-tenant
  override capability, no A2A interoperability. Every consumer of
  agent information must read Python source to learn what agents exist.

**B) Custom agent description format — a Stronghold-specific JSON
schema for agent metadata.**

- Rejected: invents what A2A Agent Cards already provide. A custom
  format loses interoperability with the A2A ecosystem and requires
  Stronghold to maintain its own schema, documentation, and tooling.
  The A2A spec is public, versioned, and supported by multiple
  platforms.

**C) All agents at the same trust tier — no per-agent trust
differentiation.**

- Rejected: violates the principle that operator-deployed agents and
  Forge-generated agents have fundamentally different trust profiles.
  An operator has reviewed and deployed their agents; a Forge-generated
  agent is LLM output that has not been reviewed. Treating them
  identically either over-trusts Forge output or under-trusts operator
  agents, both of which are wrong.

**D) Separate catalog per agent type — one registry for react agents,
another for direct agents, another for delegate agents.**

- Rejected: fragments discovery. A caller asking "what agents can
  handle this task?" would have to query multiple registries and merge
  results. A single catalog with a `strategy_type` field is simpler
  to query, simpler to maintain, and simpler to secure.

## Consequences

**Positive:**

- Every agent has a machine-readable contract (the Agent Card) that
  external systems, other agents, and the Stronghold UI can consume
  without reading Python source.
- Multi-tenant agent customization has a structured path: register an
  agent at the tenant level, and it overrides the built-in by name.
- Trust tiers are explicit per agent, so the platform can enforce
  sandboxing and audit requirements proportional to trust level.
- A2A interoperability means Stronghold agents are discoverable by any
  A2A-compatible platform.
- The registry is versionable — upgrading an agent means registering
  a new version, not overwriting the old one.

**Negative:**

- Every existing agent needs an Agent Card authored and a registry entry
  created, which is a one-time migration cost.
- The Agent Card schema is owned by the A2A specification, so
  Stronghold-specific extensions live in a `metadata` field rather than
  as first-class Card fields. This is slightly less ergonomic but
  avoids forking the spec.
- The cascade resolution (user to tenant to built-in) adds a lookup step
  to every agent dispatch. This is a Postgres query with a three-way
  COALESCE, which is fast but not free.

**Trade-offs accepted:**

- We accept the dependency on the A2A Agent Card schema in exchange for
  ecosystem interoperability and not inventing our own format.
- We accept the cascade lookup cost in exchange for clean multi-tenant
  agent customization without forking agent code.
- We accept that Forge-generated agents start at skull tier (unusable
  without promotion) in exchange for the safety guarantee that
  unreviewed LLM output never runs at elevated trust.

## References

- A2A specification: Agent Cards (agent discovery and capability
  description)
- Kubernetes documentation: "Custom Resources" and "API Conventions"
- PostgreSQL documentation: JSONB indexing and querying
- ADR-K8S-013 (hybrid execution model — agents run on both surfaces)
- ADR-K8S-014 (six-tier priority system — agents register their tier
  in their card)
- ADR-K8S-021 (tool catalog — parallel structure for tools)
