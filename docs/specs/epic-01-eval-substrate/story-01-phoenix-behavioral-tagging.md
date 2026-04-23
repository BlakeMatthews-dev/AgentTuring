# Story 1.1: Add Behavioral Tags to Phoenix Trace Spans

## User Story

As a **platform operator**, I want trace spans annotated with behavioral-failure
categories, so that I can diagnose agent performance at the category level
instead of reading individual traces.

## Background / Motivation

LangChain's eval recipe [EV-LC-DEEP-03] demonstrates that behavioral tagging
on traces enables category-level diagnosis — slicing by failure mode
(tool-selection, multi-step-reasoning, delegation-error) reveals systemic
patterns invisible in individual trace review. Stronghold already emits OTEL
spans via `phoenix_backend.py`; this story adds structured tag attributes.

## Acceptance Criteria

- AC1: Given a completed agent request, When the trace is recorded, Then the
  span includes a `stronghold.behavior_tag` attribute with at least one tag
  from the tag registry.
- AC2: Given a tag registry with 5+ categories, When a new span is created,
  Then the tag is selected by a deterministic classifier (keyword or rule-based)
  applied to the span's input/output content.
- AC3: Given a span with no classifiable content, When tagging runs, Then the
  tag defaults to `unclassified` (never empty or missing).
- AC4: Given the feature flag is disabled, When a span is created, Then no tag
  attribute is added (zero overhead).

## Test Mapping (TDD Stubs)

| AC  | Test path                        | Test function                              | Tier     |
|-----|----------------------------------|--------------------------------------------|----------|
| AC1 | tests/eval/test_tags.py          | test_span_includes_behavior_tag            | critical |
| AC2 | tests/eval/test_tags.py          | test_tag_selected_from_registry            | happy    |
| AC3 | tests/eval/test_tags.py          | test_unclassifiable_defaults_unclassified  | critical |
| AC4 | tests/eval/test_tags.py          | test_flag_disabled_no_tag_added            | happy    |

## Files to Touch

- New: `src/stronghold/eval/tags.py`
- Modify: `src/stronghold/tracing/phoenix_backend.py` (add tag attribute on span creation)

## Evidence References

- [EV-LC-DEEP-03] — behavioral tagging enables category-level diagnosis
- [EV-LC-DEEP-02] — tagging is foundation for optimization/holdout slicing

## Open Questions

- OQ-EVAL-01: Platform-defined tag categories vs per-tenant custom?
