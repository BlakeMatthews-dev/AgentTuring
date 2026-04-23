# Story 13.1: Editable Improvement Loop

## User Story

As a **platform operator**, I want the improvement loop's components (Auditor
rubric, Extractor patterns, Promoter thresholds) to be DSPy-compiled just like
task-agent prompts, so that the system improves how it improves — not just what
it improves.

## Background / Motivation

The Hyperagents paper [EV-HYPERAGENTS-02] demonstrates that self-referential
improvement (meta-agent modifying itself) produces compounding gains over time.
Stronghold's current pseudoRLHF loop has fixed topology and hand-written
components. Making each component a DSPy signature means the meta-loop itself
gets optimized from outcomes — the same optimization/holdout discipline from
Epic 01, applied one level up.

## Acceptance Criteria

- AC1: Given a DSPy meta-signature for the Auditor's review rubric, When
  compiled against Auditor outcome data, Then the compiled rubric produces
  higher inter-rater agreement on a holdout set.
- AC2: Given a DSPy meta-signature for the Extractor's pattern detection, When
  compiled, Then it detects more true fail→succeed patterns (precision+recall
  improvement on holdout).
- AC3: Given a DSPy meta-signature for the Promoter's thresholds, When
  compiled, Then promoted learnings generalize better (fewer reverts on holdout).
- AC4: Given a meta-compilation cycle, When all three components are updated,
  Then each update is versioned independently (Epic 08) and gated through
  canary (Epic 09).

## Test Mapping (TDD Stubs)

| AC  | Test path                           | Test function                                     | Tier     |
|-----|-------------------------------------|---------------------------------------------------|----------|
| AC1 | tests/meta/test_meta_signatures.py  | test_auditor_meta_signature_compiles              | critical |
| AC2 | tests/meta/test_meta_signatures.py  | test_extractor_meta_signature_compiles            | critical |
| AC3 | tests/meta/test_meta_signatures.py  | test_promoter_meta_signature_compiles             | critical |
| AC4 | tests/meta/test_meta_loop.py        | test_meta_updates_versioned_and_gated             | critical |

## Files to Touch

- New: `src/stronghold/dspy/meta_signatures.py`
- New: `src/stronghold/meta/loop.py`
- Modify: `src/stronghold/agents/feedback/loop.py` (load compiled rubric)
- Modify: `src/stronghold/memory/learnings/extractor.py` (load compiled patterns)
- Modify: `src/stronghold/memory/learnings/promoter.py` (load compiled thresholds)

## Evidence References

- [EV-HYPERAGENTS-02] — DGM-H meta-level modification is editable
- [EV-HYPERAGENTS-04] — meta-enhancements transfer across domains
- [EV-DSPY-01] — prompt-program compilation applied to meta-prompts
