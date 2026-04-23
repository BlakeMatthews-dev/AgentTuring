# Story 7.2: Harvest pseudoRLHF Outcomes as DSPy Training Data

## User Story

As a **platform operator**, I want Auditor review outcomes automatically
converted to DSPy training examples, so that the system learns from every
eval cycle without manual curation.

## Background / Motivation

The existing pseudoRLHF loop (Auditor → Extractor → Promoter → SkillForge)
already scores agent outputs and extracts fail→succeed patterns. This story
connects those outcomes to DSPy's training pipeline: each scored outcome
becomes an `(input, output, score)` triple that DSPy compilation consumes.
The LangChain recipe [EV-LC-DEEP-02] describes this as "evals as training data."

## Acceptance Criteria

- AC1: Given an Auditor review with score and feedback, When the training
  harvester runs, Then a DSPy training example is produced with input fields
  from the original request and output fields from the agent's response.
- AC2: Given a harvested example, When it has a score >= threshold, Then it
  is labeled as a positive example.
- AC3: Given a harvested example, When it has a score < threshold, Then it
  is labeled as a negative example (or excluded, configurable).
- AC4: Given harvested examples, When behavioral tags exist (Epic 01), Then
  each example includes its tag for stratified sampling.

## Test Mapping (TDD Stubs)

| AC  | Test path                       | Test function                                | Tier     |
|-----|---------------------------------|----------------------------------------------|----------|
| AC1 | tests/dspy/test_training.py     | test_auditor_outcome_to_training_example     | critical |
| AC2 | tests/dspy/test_training.py     | test_high_score_labeled_positive             | happy    |
| AC3 | tests/dspy/test_training.py     | test_low_score_labeled_negative              | happy    |
| AC4 | tests/dspy/test_training.py     | test_behavioral_tag_included_in_example      | happy    |

## Files to Touch

- New: `src/stronghold/dspy/training.py`
- Modify: `src/stronghold/memory/learnings/extractor.py` (emit DSPy-compatible events)

## Evidence References

- [EV-LC-DEEP-02] — evals as training data
- [EV-DSPY-01] — compilation from examples + metrics
