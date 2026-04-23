# Epic 11: Group Chat Patterns

## Summary

Introduce agent interaction patterns beyond single-agent dispatch: debate,
committee review, collaborative iteration. Scribe debate is the first pattern
(lowest stakes — writing, not code/security). New patterns are added one at a
time per the incremental rollout rule. The Conduit (Epic 06) selects patterns
based on intent class; pattern effectiveness feeds back into the DSPy/eval loop.

## Why Now

Epic 05 (Agents-as-Tools) provides the invocation primitive. Epic 09 (Canary +
Tournament) provides the promotion gate. New patterns can be introduced safely:
the Conduit picks them, the Tournament validates them, canary catches
regressions.

## Depends On

- Epic 05 (Agents-as-Tools) — debate participants call each other
- Epic 09 (Canary + Tournament) — new patterns gate on tournament

## Blocks

None directly.

## Ship Gate

Scribe debate (research → draft → critique → revise) produces higher-rated
output than single-pass Scribe on a holdout writing eval set.

## Roles Affected

| Role | Impact |
|------|--------|
| Agent author | Can define multi-agent interaction patterns |
| End user | Sees higher-quality writing output |

## Evidence References

- [EV-LC-DEEP-05] — model decides interaction pattern, not infrastructure
- [EV-HYPERAGENTS-01] — multi-agent composition patterns

## Files Touched

### New Files
- `src/stronghold/agents/patterns/__init__.py`
- `src/stronghold/agents/patterns/debate.py` — debate protocol primitive
- `src/stronghold/agents/patterns/registry.py` — pattern registry for Conduit
- `tests/agents/debate/test_debate_protocol.py`
- `tests/agents/debate/test_scribe_debate.py`

### Modified Files
- `src/stronghold/conduit/reasoning.py` — pattern selection as a reasoning tool
- `agents/scribe/agent.yaml` — add debate pattern configuration

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_DEBATE_PATTERN_ENABLED`
- **Canary cohort**: Scribe writing requests only
- **Rollback plan**: Disable flag; Scribe uses single-pass (current behavior)
- **Release rule**: One new pattern per release maximum

## Open Questions

- OQ-DEBATE-01: Convergence criterion (fixed rounds, quality threshold, judge)
- OQ-DEBATE-02: Maximum debate participants
