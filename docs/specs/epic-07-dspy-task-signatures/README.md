# Epic 07: DSPy Task Signatures

## Summary

Integrate DSPy as the prompt-optimization substrate. Define DSPy signatures for
key prompts across the system — Conduit routing, Mason planner, Auditor review
rubric. Harvest pseudoRLHF outcomes (Auditor → Extractor) as training data for
DSPy compilation. Store compiled prompts with cache and pinning support.

## Why Now

Epic 01 (Eval Substrate) provides the optimization/holdout infrastructure. This
epic operationalizes it: DSPy compiles better prompts from eval outcomes instead
of relying on hand-written prompt engineering. This is the mechanism that makes
skill-score improvement (Epic 02) and Conduit reasoning (Epic 06) systematically
improvable rather than manually tuned.

## Depends On

- Epic 01 (Eval Substrate) — training data and holdout validation

## Blocks

- Epic 08 (Prompt Versioning) — DSPy-compiled prompts need version tracking
- Epic 13 (Hyperagents Meta-Level) — meta-level signatures wrap task-level ones

## Ship Gate

A DSPy-compiled prompt for one agent outperforms the hand-written version on
the holdout eval set.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Runs DSPy compilation jobs, reviews compiled vs hand-written |
| Agent author | Defines DSPy signatures for their agent's key prompts |

## Evidence References

- [EV-DSPY-01] — prompt-program compilation from examples + metrics
- [EV-DSPY-02] — signatures as typed input→output contracts
- [EV-DSPY-03] — optimizers (BootstrapFewShot, MIPRO)
- [EV-LC-DEEP-02] — evals as training data for harness improvement

## Files Touched

### New Files
- `src/stronghold/dspy/__init__.py`
- `src/stronghold/dspy/signatures.py` — DSPy signature definitions per agent
- `src/stronghold/dspy/training.py` — harvest pseudoRLHF outcomes as training examples
- `src/stronghold/dspy/compiler.py` — DSPy compilation runner, optimizer selection
- `src/stronghold/dspy/cache.py` — compiled prompt cache with pinning
- `tests/dspy/test_signatures.py`
- `tests/dspy/test_training.py`
- `tests/dspy/test_compiler.py`
- `tests/dspy/test_cache.py`

### Modified Files
- `src/stronghold/memory/learnings/extractor.py` — emit training examples for DSPy
- `src/stronghold/agents/base.py` — load compiled prompt if available, else hand-written
- `src/stronghold/container.py` — register DSPy compiler

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_DSPY_ENABLED`
- **Canary cohort**: Single agent (Mason planner) for first compilation cycle
- **Rollback plan**: Disable flag; agents load hand-written prompts (no DSPy consultation)

## Open Questions

- OQ-DSPY-01: Runtime vs ahead-of-time compilation — where is the cache?
- OQ-DSPY-02: Which optimizer to start with (BootstrapFewShot vs MIPRO)?
