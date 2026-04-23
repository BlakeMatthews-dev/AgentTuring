# Epic 10: Mid-Session Model Switching

## Summary

Generalize model switching beyond timeout-only fallback. The Conduit reasoning
agent (Epic 06) can re-route to a different model on any signal: cost threshold,
quality drop, latency spike, token-budget exhaustion, or explicit capability
need. Conversation continuity is preserved across the switch.

## Why Now

Epic 06 (Conduit-as-Reasoning-Agent) makes the Conduit a reasoning agent that
can re-evaluate decisions per turn. Model switching is one such decision — the
Conduit sees the CostVector and can downshift to a cheaper model for simple
follow-ups or upshift for complex reasoning.

## Depends On

- Epic 06 (Conduit-as-Reasoning-Agent)

## Blocks

None directly.

## Ship Gate

Conduit switches model mid-session on a cost signal. Conversation continues
without loss. Trace span records the switch reason.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Configures switch triggers and thresholds |
| End user | Transparent — conversation continuity preserved |

## Evidence References

- [EV-FRUGAL-01] — cheap-first escalation, cost-aware model cascading
- [EV-ANTHROPIC-01] — prompt caching / KV reuse optimization across model switches

## Files Touched

### New Files
- `src/stronghold/routing/switching.py` — switch triggers, continuity contract
- `tests/routing/test_switching.py`

### Modified Files
- `src/stronghold/conduit/reasoning.py` — integrate switch decision into reasoning loop
- `src/stronghold/router/selector.py` — expose switch candidates for current session

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_MODEL_SWITCHING_ENABLED`
- **Canary cohort**: Internal dev org
- **Rollback plan**: Disable flag; model stays fixed per-session (current behavior except timeout)

## Open Questions

- OQ-SWITCH-01: Continuity contract ownership (calling agent vs Conduit)
