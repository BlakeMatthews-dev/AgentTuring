# Epic 06: Conduit-as-Reasoning-Agent

## Summary

Refactor the Conduit from a heuristic router (classify → lookup table → dispatch)
into a reasoning agent that calls other agents as tools. Strategy selection
becomes the Conduit's reasoning, not a dispatch-time switch. The heuristic
router becomes a fallback behind a feature flag.

## Why Now

Epic 05 (Agents-as-Tools) provides the invocation primitive. This epic uses it:
the Conduit becomes a reasoning agent whose tools are the agent roster. It sees
CapabilityProfiles, makes economic delegation decisions, and can re-route
mid-session on any signal (latency, cost, quality, tool failure).

## Depends On

- Epic 05 (Agents-as-Tools)

## Blocks

- Epic 10 (Mid-Session Model Switching) — Conduit reasoning enables per-turn re-routing
- Epic 14 (Artificer v2) — learnings from Conduit reasoning inform v2 design

## Ship Gate

Conduit reasoning loop replaces heuristic router for a test cohort. Routing
decisions are logged as trace spans. Fallback to heuristic router on flag-off
works without data loss.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Monitors Conduit reasoning traces; tunes reasoning budget |
| End user | Transparent — same API, potentially better routing |
| Agent author | Agents surfaced to Conduit via CapabilityProfile descriptors |

## Evidence References

- [EV-LC-DEEP-05] — model decides when to plan, when to delegate
- [EV-LG-01] — graph-based orchestration with conditional routing
- [EV-HYPERAGENTS-01] — meta-agent calling task-agents through uniform interface

## Files Touched

### New Files
- `src/stronghold/conduit/reasoning.py` — reasoning loop, agent-call tool bindings
- `src/stronghold/conduit/fallback.py` — extracted heuristic router (current conduit.py logic)
- `tests/conduit/test_reasoning_loop.py`
- `tests/conduit/test_reasoning_fallback.py`

### Modified Files
- `src/stronghold/conduit.py` — delegate to reasoning.py or fallback.py based on flag
- `src/stronghold/agents/strategies/delegate.py` — may be deprecated in favor of Conduit reasoning
- `src/stronghold/agents/strategies/plan_execute.py` — may be deprecated (Conduit plans via reasoning)

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_CONDUIT_REASONING_ENABLED`
- **Canary cohort**: 5% of internal org traffic
- **Rollback plan**: Disable flag; Conduit falls back to heuristic router (extracted to fallback.py)

## Open Questions

- OQ-CONDUIT-01: Fallback behavior when reasoning loop diverges or exceeds cost budget
- OQ-CONDUIT-02: Maximum reasoning turns before forced response
