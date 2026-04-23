# Story 1.5: Eval Report Artifact

## User Story

As a **platform operator**, I want eval runs to produce a standardized report
artifact, so that I can compare runs over time, gate promotions, and audit
eval history.

## Background / Motivation

The LangChain recipe [EV-LC-DEEP-02] emphasizes baseline → experiment →
validate as a repeatable loop. A standardized report artifact makes each step
comparable. The Hyperagents paper [EV-HYPERAGENTS-03] saves metadata per
generation including evaluation success, parent validity, and genealogy — the
same principle applied to eval history.

## Acceptance Criteria

- AC1: Given a completed eval run, When the report is generated, Then it
  includes: run_id, timestamp, agent_name, dataset_name, split (optimization
  or holdout), overall_score, per_tag_scores, per_sample_results.
- AC2: Given two report artifacts, When compared, Then delta scores per tag
  are computable (report B - report A per category).
- AC3: Given a report artifact, When serialized and deserialized, Then all
  fields round-trip without loss.
- AC4: Given a report with per-tag scores, When a regression is detected (tag
  score drops > threshold), Then the report flags the regressed tags.

## Test Mapping (TDD Stubs)

| AC  | Test path                        | Test function                              | Tier     |
|-----|----------------------------------|--------------------------------------------|----------|
| AC1 | tests/eval/test_report.py        | test_report_includes_required_fields       | critical |
| AC2 | tests/eval/test_report.py        | test_report_delta_computation              | happy    |
| AC3 | tests/eval/test_report.py        | test_report_serialization_roundtrip        | critical |
| AC4 | tests/eval/test_report.py        | test_report_flags_regression               | happy    |

## Files to Touch

- New: `src/stronghold/eval/report.py`

## Evidence References

- [EV-LC-DEEP-02] — baseline → experiment → validate loop needs comparable artifacts
- [EV-HYPERAGENTS-03] — genealogy/metadata tracking per generation
