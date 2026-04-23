# Epic 13: Hyperagents Meta-Level Self-Improvement

## Summary

Make the improvement loop itself an editable program. DSPy optimizes not just
task-agent prompts (Mason's planner, Scribe's committee) but the meta-level
components: Auditor's review rubric, Extractor's fail→succeed pattern detection,
Promoter's hit-count thresholds, and SkillForge's mutation template. This is
the self-referential improvement loop from the Hyperagents paper — improvements
to the improvement process compound over time. A safety circuit breaker freezes
self-mutation if the rate exceeds a configured threshold.

## Why Now

Epics 07 (DSPy), 08 (Prompt Versioning), and 09 (Canary + Tournament) provide
the three prerequisites: an optimization mechanism, a safety net for reversal,
and a staged promotion gate. Without all three, meta-level self-modification is
too risky for production. With all three, it becomes the highest-leverage
improvement the system can make.

## Depends On

- Epic 07 (DSPy Task Signatures) — DSPy signatures for meta components
- Epic 08 (Prompt Versioning) — rollback safety net
- Epic 09 (Canary + Tournament) — staged promotion gate

## Blocks

- Epic 14 (Artificer v2 Rethink) — meta-level learnings inform v2 design

## Ship Gate

DSPy optimizes the Auditor's review rubric. The compiled rubric outperforms
the hand-written version on holdout. Meta circuit breaker fires when test
simulates rapid self-mutation.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Monitors meta-improvement loop; configures circuit breaker |
| Security auditor | Reviews meta-mutation audit trail |

## Evidence References

- [EV-HYPERAGENTS-01] — meta-agent modifies both task-agent and itself
- [EV-HYPERAGENTS-02] — DGM-H: meta-level modification procedure is editable
- [EV-HYPERAGENTS-03] — meta-enhancements accumulate across runs and domains
- [EV-HYPERAGENTS-04] — meta-level improvements transfer across domains

## Files Touched

### New Files
- `src/stronghold/meta/__init__.py`
- `src/stronghold/meta/loop.py` — meta-improvement loop orchestrator
- `src/stronghold/meta/circuit_breaker.py` — safety freeze on rapid mutation
- `src/stronghold/dspy/meta_signatures.py` — DSPy signatures for Auditor, Extractor, Promoter
- `tests/meta/test_meta_loop.py`
- `tests/meta/test_circuit_breaker.py`
- `tests/meta/test_meta_signatures.py`

### Modified Files
- `src/stronghold/memory/learnings/extractor.py` — extractor prompt becomes DSPy-compiled
- `src/stronghold/memory/learnings/promoter.py` — promotion threshold becomes DSPy-optimized
- `src/stronghold/agents/feedback/loop.py` — Auditor rubric becomes DSPy-compiled
- `src/stronghold/skills/forge.py` — mutation template becomes DSPy-compiled

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_META_IMPROVEMENT_ENABLED`
- **Canary cohort**: Auditor rubric only (single meta-component first)
- **Rollback plan**: Disable flag; all meta-components use hand-written prompts
- **Circuit breaker**: Auto-disables flag if > N mutations per hour (configurable)

## Open Questions

- OQ-META-01: Circuit breaker threshold (mutations per hour/day)
- OQ-META-02: Does rolling back a meta-change also roll back its downstream task-level changes?
