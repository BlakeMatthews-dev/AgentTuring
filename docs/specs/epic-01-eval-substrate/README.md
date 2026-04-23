# Epic 01: Eval Substrate

## Summary

Build the measurement infrastructure that every other epic depends on: behavioral
tagging on Phoenix trace spans, optimization/holdout dataset management, SWE-bench
adapter for coding-loop benchmarks, Inspect AI adapter for general evals, and a
standardized eval-report artifact. Without this, no subsequent epic can claim
"we did not regress."

## Why Now

This is the foundation. Every other epic's ship gate includes "passes eval
against holdout set." Without eval infrastructure, promotion (Tournament, Canary,
DSPy, Hyperagents meta-level) is gated on heuristics instead of evidence.

## Depends On

None — this is the root of the dependency graph.

## Blocks

All other epics (02–14). Every ship gate references eval pass/fail signals
produced by this epic's infrastructure.

## Ship Gate

- Behavioral tags emit on Phoenix spans for at least 5 tag categories
- One optimization/holdout split passes end-to-end (create dataset → run eval →
  score → report)
- At least one SWE-bench instance runs through the adapter

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Configures eval datasets, reviews reports |
| Agent author | Sees behavioral-tag breakdowns for their agent |
| Security auditor | Audits eval dataset provenance and split integrity |

## Evidence References

- [EV-LC-DEEP-02] Six-phase eval loop with optimization/holdout splits
- [EV-LC-DEEP-03] Behavioral tagging enables category-level diagnosis
- [EV-LC-DEEP-04] Holdout prevents overfitting
- [EV-SWEBENCH-01] Standard coding-agent benchmark
- [EV-INSPECT-01] Solver/scorer/dataset abstraction
- [EV-INSPECT-02] Sandbox per eval sample

## Files Touched

### New Files
- `src/stronghold/eval/__init__.py`
- `src/stronghold/eval/tags.py` — behavioral tag definitions and span annotation
- `src/stronghold/eval/dataset.py` — dataset management (create, split, load)
- `src/stronghold/eval/runner.py` — eval execution loop
- `src/stronghold/eval/scorer.py` — scorer protocol + built-in scorers
- `src/stronghold/eval/report.py` — eval report artifact generation
- `src/stronghold/eval/swebench_adapter.py` — SWE-bench dataset + scoring adapter
- `src/stronghold/eval/inspect_adapter.py` — Inspect AI framework adapter
- `tests/eval/test_tags.py`
- `tests/eval/test_dataset.py`
- `tests/eval/test_runner.py`
- `tests/eval/test_scorer.py`
- `tests/eval/test_report.py`
- `tests/eval/test_swebench_adapter.py`
- `tests/eval/test_inspect_adapter.py`

### Modified Files
- `src/stronghold/tracing/phoenix_backend.py` — add behavioral-tag span attributes
- `src/stronghold/protocols/` — add `EvalRunner`, `EvalScorer`, `EvalDataset` protocols
- `tests/fakes.py` — add `FakeEvalRunner`, `FakeEvalScorer`

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_EVAL_SUBSTRATE_ENABLED`
- **Canary cohort**: Internal dev org only (eval runs are read-only, no prod impact)
- **Rollback plan**: Disable flag; spans still emit without tags (no-op tag layer)

## Open Questions

- OQ-EVAL-01: Tag schema owner (platform vs per-tenant)
- OQ-EVAL-02: SWE-bench subset selection
- OQ-EVAL-03: Eval artifact storage backend
