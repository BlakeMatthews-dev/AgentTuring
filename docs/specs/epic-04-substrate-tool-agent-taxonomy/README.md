# Epic 04: Substrate / Tool / Agent Taxonomy

## Summary

Formalize the three-tier execution model: **substrate** (LLM inference +
deterministic pure utilities, available to all agents, not permissioned),
**tools** (permissioned side effects, heavy agents only), and **agents**
(callable units, any agent can call permitted agents). Introduce the `kind`
field on agent definitions (`light` or `heavy`) and enforce: light agents have
zero tools and may only call other agents or use substrate.

## Why Now

Epic 03 (Agent-Call ACLs) defined who can call whom. This epic enforces the
structural constraint: light agents have NO tools. When they need side effects,
they call a heavy agent. This is the key governance principle that ensures every
side effect in the system originates from an auditable heavy agent with a
container.

## Depends On

- Epic 03 (Agent-Call ACLs)

## Blocks

- Epic 05 (Agents-as-Tools) — tool adapter needs the taxonomy to generate descriptors

## Ship Gate

A `kind: light` agent runs in the test harness with zero tools. Attempting to
register a tool on a light agent raises a validation error.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Understands deployment topology (heavy pods vs light pool) |
| Agent author | Chooses `kind: light` or `kind: heavy` at authoring time |
| Security auditor | Verifies light agents have no tool access |

## Evidence References

- [EV-OH-01] — permission modes for different agent classes
- [EV-HYPERAGENTS-01] — meta-agent (light, orchestration-only) vs task-agent (heavy, tools)

## Files Touched

### New Files
- `src/stronghold/capability/taxonomy.py` — AgentKind enum, validation functions
- `tests/taxonomy/test_taxonomy.py`
- `tests/taxonomy/test_light_agent_contract.py`

### Modified Files
- `src/stronghold/agents/factory.py` — validate kind field, enforce tool constraints
- `agents/*/agent.yaml` — add `kind: heavy` or `kind: light` field
- `src/stronghold/types/agent.py` — add kind to AgentIdentity

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_AGENT_TAXONOMY_ENABLED`
- **Canary cohort**: Internal dev org
- **Rollback plan**: Disable flag; factory ignores kind field (all agents treated as heavy, same as today)

## Open Questions

- OQ-TAX-01: Does substrate include deterministic HTTP clients?
- OQ-TAX-02: Can a light agent be promoted to heavy at runtime?
