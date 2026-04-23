# Story 2.1: CapabilityProfile Schema

## User Story

As an **agent author**, I want a structured schema for declaring an agent's
capabilities with permission, skill, and cost dimensions, so that reasoning
agents can make informed delegation decisions.

## Background / Motivation

The CapabilityProfile separates three concerns most systems collapse: permission
(can you?), skill (should you?), and cost (what does it consume?). The
Hyperagents paper [EV-HYPERAGENTS-02] demonstrates per-capability scoring. The
skill dimension is intent-conditional — Scribe is skill 10 at long-form prose
but skill 4 at terse changelogs. Cost includes container standing cost, not
just per-call inference tokens.

## Acceptance Criteria

- AC1: Given a CapabilityProfile with all three dimensions populated, When
  validated, Then it passes schema validation without errors.
- AC2: Given a profile missing the skill dimension, When validated, Then it
  raises a validation error identifying the missing field.
- AC3: Given a profile with intent-conditional skill scores (nested JSON:
  `{summary: 4, report: 1, prose: 2}`), When accessed for intent "summary",
  Then it returns skill score 4.
- AC4: Given a profile with a CostVector, When the standing cost is queried,
  Then it returns the container resource cost (cpu, mem, replicas_min).
- AC5: Given a profile with permission=BLOCKED for a capability, When the
  profile is surfaced to a reasoning agent, Then the blocked capability is
  omitted from the visible options.

## Test Mapping (TDD Stubs)

| AC  | Test path                                | Test function                                    | Tier     |
|-----|------------------------------------------|--------------------------------------------------|----------|
| AC1 | tests/capability/test_profile_schema.py  | test_full_profile_validates                      | critical |
| AC2 | tests/capability/test_profile_schema.py  | test_missing_skill_raises_validation_error       | critical |
| AC3 | tests/capability/test_profile_schema.py  | test_intent_conditional_skill_lookup             | critical |
| AC4 | tests/capability/test_profile_schema.py  | test_cost_vector_includes_standing_resources     | happy    |
| AC5 | tests/capability/test_profile_schema.py  | test_blocked_capability_omitted_from_visible     | critical |

## Files to Touch

- New: `src/stronghold/capability/profile.py`
- New: `src/stronghold/types/capability.py` (if separate from profile.py)

## Evidence References

- [EV-HYPERAGENTS-02] — per-capability scoring
- [EV-FRUGAL-01] — cost-aware model/agent selection
