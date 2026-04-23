# Story 4.3: Substrate Interface — Free Capabilities for All Agents

## User Story

As an **agent author**, I want substrate capabilities (LLM inference,
deterministic utilities like time/UUID/hashing) available to all agents without
permission gating, so that light agents can still reason, generate text, and
use pure functions without calling a heavy agent for trivial operations.

## Background / Motivation

Substrate is the fabric agents exist within — not a permissioned resource.
LLM inference is how agents think; deterministic utilities are pure functions
with no side effects. Gating these behind tool permissions would force light
agents to call heavy agents for `get_current_time()`, which is wasteful.

## Acceptance Criteria

- AC1: Given a light agent, When it uses LLM inference (its reasoning loop),
  Then no tool permission is checked.
- AC2: Given a substrate utility registry with [get_time, generate_uuid, hash],
  When a light agent calls `get_time()`, Then it returns the current time
  without a tool-permission check.
- AC3: Given a substrate utility, When it attempts any side effect (file I/O,
  network, process spawn), Then it is rejected at registration time (substrate
  utilities must be pure).
- AC4: Given a utility that makes HTTP calls (e.g., geocoding), When registered,
  Then it is rejected as a substrate utility (HTTP = side effect = requires
  heavy agent or tool).

## Test Mapping (TDD Stubs)

| AC  | Test path                                    | Test function                                 | Tier     |
|-----|----------------------------------------------|-----------------------------------------------|----------|
| AC1 | tests/taxonomy/test_taxonomy.py              | test_light_agent_llm_no_permission_check      | critical |
| AC2 | tests/taxonomy/test_taxonomy.py              | test_substrate_utility_no_permission_check     | happy    |
| AC3 | tests/taxonomy/test_taxonomy.py              | test_impure_utility_rejected_at_registration  | critical |
| AC4 | tests/taxonomy/test_taxonomy.py              | test_http_utility_rejected_as_substrate       | happy    |

## Files to Touch

- New: `src/stronghold/capability/substrate.py` — substrate utility registry, purity validation
- Modify: `src/stronghold/tools/registry.py` (distinguish substrate vs tool registration)

## Evidence References

- [EV-PI-03] — minimal substrate, extensible capabilities
