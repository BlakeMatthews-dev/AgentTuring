# Story 1.2: Optimization/Holdout Dataset Splits

## User Story

As an **agent author**, I want eval datasets split into optimization and holdout
sets, so that I can validate that prompt improvements generalize to unseen
examples and do not overfit.

## Background / Motivation

LangChain's recipe [EV-LC-DEEP-02] treats evals as training data with classical
ML discipline: optimization sets drive changes, holdout sets validate
generalization. Without this split, SkillForge promotions and DSPy compilations
can overfit to the cases that triggered them. The Hyperagents paper
[EV-HYPERAGENTS-03] uses staged evaluation (small sample → full) as the same
principle applied to generational evolution.

## Acceptance Criteria

- AC1: Given a list of eval examples, When `create_split(examples, holdout_pct=0.2)`
  is called, Then two disjoint sets are returned with correct proportions.
- AC2: Given a split dataset, When `get_optimization_set()` is called, Then only
  optimization examples are returned (never holdout).
- AC3: Given a split dataset, When `get_holdout_set()` is called, Then only
  holdout examples are returned (never optimization).
- AC4: Given tagged eval examples, When splitting, Then tag distribution is
  preserved across both sets (stratified split).
- AC5: Given a persisted dataset, When loaded later, Then the same split is
  reproduced (deterministic seed).

## Test Mapping (TDD Stubs)

| AC  | Test path                          | Test function                                 | Tier     |
|-----|------------------------------------|-----------------------------------------------|----------|
| AC1 | tests/eval/test_dataset.py         | test_split_produces_disjoint_sets             | critical |
| AC2 | tests/eval/test_dataset.py         | test_optimization_set_excludes_holdout        | critical |
| AC3 | tests/eval/test_dataset.py         | test_holdout_set_excludes_optimization        | critical |
| AC4 | tests/eval/test_dataset.py         | test_stratified_split_preserves_tag_dist      | happy    |
| AC5 | tests/eval/test_dataset.py         | test_split_deterministic_with_seed            | happy    |

## Files to Touch

- New: `src/stronghold/eval/dataset.py`

## Evidence References

- [EV-LC-DEEP-02] — optimization/holdout split methodology
- [EV-LC-DEEP-04] — holdout prevents overfitting
- [EV-HYPERAGENTS-03] — staged evaluation principle
