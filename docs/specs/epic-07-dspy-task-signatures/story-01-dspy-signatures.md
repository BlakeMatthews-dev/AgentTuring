# Story 7.1: DSPy Signature Definitions

## User Story

As an **agent author**, I want my agent's key prompts defined as typed DSPy
signatures, so that DSPy can optimize them systematically from eval outcomes
rather than requiring manual prompt engineering.

## Background / Motivation

DSPy [EV-DSPY-02] treats prompts as typed programs: `input fields → output
fields` with optional constraints. Defining signatures makes prompts a
structured optimization target. Each agent's critical prompt becomes a DSPy
module that can be compiled against training data.

## Acceptance Criteria

- AC1: Given a DSPy signature for Mason's planner, When instantiated, Then it
  accepts `{task_description, codebase_context}` and returns
  `{plan_steps, estimated_complexity}`.
- AC2: Given a DSPy signature for Auditor's review rubric, When instantiated,
  Then it accepts `{agent_output, task_description}` and returns
  `{score, feedback, failure_categories}`.
- AC3: Given a DSPy signature for Conduit routing, When instantiated, Then it
  accepts `{user_request, agent_profiles}` and returns
  `{selected_agent, reasoning}`.
- AC4: Given a signature, When compiled with training examples, Then the
  compiled version is a drop-in replacement for the hand-written prompt.

## Test Mapping (TDD Stubs)

| AC  | Test path                          | Test function                               | Tier     |
|-----|------------------------------------|---------------------------------------------|----------|
| AC1 | tests/dspy/test_signatures.py      | test_mason_planner_signature_shape          | critical |
| AC2 | tests/dspy/test_signatures.py      | test_auditor_rubric_signature_shape         | critical |
| AC3 | tests/dspy/test_signatures.py      | test_conduit_routing_signature_shape        | critical |
| AC4 | tests/dspy/test_signatures.py      | test_compiled_signature_is_drop_in          | happy    |

## Files to Touch

- New: `src/stronghold/dspy/signatures.py`

## Evidence References

- [EV-DSPY-02] — signatures as typed input→output contracts
