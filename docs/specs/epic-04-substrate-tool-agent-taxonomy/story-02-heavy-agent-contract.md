# Story 4.2: Heavy Agent Contract — Container, Tools, Side Effects

## User Story

As a **platform operator**, I want heavy agents to declare their container
resource requirements alongside their tool permissions, so that I can plan K8s
deployment topology and cost attribution.

## Background / Motivation

Heavy agents are the only entities in the system that produce side effects.
They have containers with resource reservations (CPU, memory, GPU), tools with
permission boundaries, and scaling profiles. Their CostVector (from Epic 02)
includes standing container cost — the most important dimension for deployment
planning.

## Acceptance Criteria

- AC1: Given an agent.yaml with `kind: heavy` and `tools: [file_read, file_write]`,
  When loaded, Then it registers with all declared tools available.
- AC2: Given a heavy agent, When its CostVector is queried, Then it includes
  `standing: {cpu, mem, replicas_min, replicas_max}` from deployment config.
- AC3: Given a heavy agent YAML without `kind` field (legacy), When loaded,
  Then it defaults to `kind: heavy` (backward compatible).

## Test Mapping (TDD Stubs)

| AC  | Test path                                    | Test function                                 | Tier     |
|-----|----------------------------------------------|-----------------------------------------------|----------|
| AC1 | tests/taxonomy/test_taxonomy.py              | test_heavy_agent_registers_with_tools         | critical |
| AC2 | tests/taxonomy/test_taxonomy.py              | test_heavy_cost_vector_includes_standing      | happy    |
| AC3 | tests/taxonomy/test_taxonomy.py              | test_missing_kind_defaults_heavy              | critical |

## Files to Touch

- Modify: `src/stronghold/capability/taxonomy.py` (AgentKind enum, default)
- Modify: `src/stronghold/agents/factory.py` (default kind=heavy for legacy)

## Evidence References

- [EV-FRUGAL-01] — cost-aware deployment needs resource declarations
