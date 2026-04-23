# Epic 09: Canary + A/B Tournament

## Summary

Extend the existing Tournament system (Elo, K=32, 10K in-memory records) with
staged promotion: canary → A/B → full rollout. A candidate version serves a
small traffic cohort; if it passes holdout eval without regression, it graduates
to A/B against the incumbent; if it wins the tournament, it promotes to full.
Auto-rollback on regression.

## Why Now

Epics 07-08 introduce automated prompt mutation and versioning. This epic gates
those mutations: no change reaches full production without surviving staged
evaluation. The Hyperagents paper [EV-HYPERAGENTS-03] uses staged evaluation
(small sample → full eval) as the same principle.

## Depends On

- Epic 01 (Eval Substrate) — holdout evaluation for promotion gate
- Epic 08 (Prompt Versioning) — versions to promote and rollback to

## Blocks

- Epic 11 (Group Chat Patterns) — new patterns gate on tournament before default
- Epic 13 (Hyperagents Meta-Level) — meta-changes gate on tournament
- Epic 14 (Artificer v2) — v2 candidate gates on tournament

## Ship Gate

A candidate prompt version passes canary (small cohort holdout eval), survives
A/B tournament against incumbent, and auto-promotes. A regressing candidate
auto-rolls back.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Monitors canary/A/B status, configures cohort % |
| Agent author | Sees their agent's tournament history |

## Evidence References

- [EV-HYPERAGENTS-03] — staged evaluation (small sample → full eval)
- [EV-LC-DEEP-02] — regression protection via designated eval subsets

## Files Touched

### New Files
- `src/stronghold/agents/canary_manager.py` — canary cohort routing, staged promotion logic
- `tests/tournament/test_canary_promotion.py`
- `tests/tournament/test_ab_tournament.py`

### Modified Files
- `src/stronghold/agents/tournament.py` — add persistence, A/B mode, auto-rollback
- `src/stronghold/prompts/versioning/store.py` — tournament reads version metadata

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_CANARY_TOURNAMENT_ENABLED`
- **Canary cohort**: Meta — the canary system itself canaries on a single agent first
- **Rollback plan**: Disable flag; all changes promote immediately (current behavior)

## Open Questions

- OQ-CANARY-01: Naming collision with existing `skills/canary.py`
- OQ-CANARY-02: Traffic percentage for canary cohort
