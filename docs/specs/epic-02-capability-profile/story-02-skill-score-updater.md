# Story 2.2: Skill-Score Updater from Eval Outcomes

## User Story

As a **platform operator**, I want skill scores to update automatically from
eval outcomes, so that the CapabilityProfile reflects real measured competence
rather than hand-declared priors.

## Background / Motivation

Declared skill priors (e.g., "Scribe write_text skill=10") are starting guesses.
The pseudoRLHF loop (Auditor → Extractor → Promoter) already scores agent
outputs. This story connects those scores to the CapabilityProfile so skill
values converge toward empirical reality. DSPy [EV-DSPY-01] operationalizes
this as prompt-program compilation from examples + metrics.

## Acceptance Criteria

- AC1: Given an eval outcome with agent_name, capability, intent_class, and
  score, When the updater runs, Then the skill score for that
  (agent, capability, intent_class) tuple is updated using exponential moving
  average (EMA).
- AC2: Given no eval outcomes for a capability, When the updater runs, Then the
  skill score remains at its declared prior (no decay in v1).
- AC3: Given 10+ eval outcomes, When the updater runs, Then the updated skill
  score is closer to the mean outcome score than the original prior.
- AC4: Given eval outcomes from multiple orgs, When the updater runs, Then
  scores are computed per-org (tenant isolation preserved).

## Test Mapping (TDD Stubs)

| AC  | Test path                              | Test function                                  | Tier     |
|-----|----------------------------------------|------------------------------------------------|----------|
| AC1 | tests/capability/test_updater.py       | test_ema_updates_skill_from_outcome            | critical |
| AC2 | tests/capability/test_updater.py       | test_no_outcomes_preserves_prior               | happy    |
| AC3 | tests/capability/test_updater.py       | test_convergence_after_many_outcomes           | happy    |
| AC4 | tests/capability/test_updater.py       | test_per_org_isolation                         | critical |

## Files to Touch

- New: `src/stronghold/capability/updater.py`
- Modify: `src/stronghold/eval/runner.py` (emit outcome events for updater)

## Evidence References

- [EV-DSPY-01] — prompt-program compilation from examples + metrics
- [EV-HYPERAGENTS-03] — generational evolution with scored outcomes
