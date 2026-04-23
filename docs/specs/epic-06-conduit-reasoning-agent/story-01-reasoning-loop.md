# Story 6.1: Conduit Reasoning Loop

## User Story

As a **platform operator**, I want the Conduit to reason about which agent to
call rather than following a lookup table, so that routing decisions are
intelligent, traceable, and improvable via DSPy/eval.

## Background / Motivation

The current Conduit (767 lines, `conduit.py`) follows: classify intent → lookup
agent in table → dispatch. This is fast but not learnable — a heuristic router
has nothing to optimize. Making the Conduit a reasoning agent that sees
CapabilityProfiles and calls agents as tools turns routing into a traceable
decision that DSPy (Epic 07) and the Hyperagents meta-loop (Epic 13) can
optimize. [EV-LC-DEEP-05, EV-HYPERAGENTS-01]

## Acceptance Criteria

- AC1: Given a user request, When the Conduit reasoning loop runs, Then it
  emits at least one `call_agent` tool call to a roster agent.
- AC2: Given CapabilityProfiles for three agents, When the Conduit reasons,
  Then its trace includes the profiles it considered (logged as span attributes).
- AC3: Given a request that matches Ranger (search) and Scribe (writing), When
  the Conduit reasons, Then it routes to the agent with the higher skill score
  for the detected intent.
- AC4: Given the reasoning loop exceeds `max_reasoning_turns`, When the limit
  is hit, Then it returns the best available response (not an error).
- AC5: Given the feature flag is off, When a request arrives, Then the
  heuristic router handles it (zero behavior change from current prod).

## Test Mapping (TDD Stubs)

| AC  | Test path                                | Test function                                  | Tier     |
|-----|------------------------------------------|-------------------------------------------------|----------|
| AC1 | tests/conduit/test_reasoning_loop.py     | test_reasoning_emits_call_agent                 | critical |
| AC2 | tests/conduit/test_reasoning_loop.py     | test_profiles_logged_in_trace                   | happy    |
| AC3 | tests/conduit/test_reasoning_loop.py     | test_routes_to_higher_skill_agent               | critical |
| AC4 | tests/conduit/test_reasoning_loop.py     | test_max_turns_returns_best_response            | critical |
| AC5 | tests/conduit/test_reasoning_fallback.py | test_flag_off_uses_heuristic_router             | critical |

## Files to Touch

- New: `src/stronghold/conduit/reasoning.py`
- New: `src/stronghold/conduit/fallback.py` (extract from conduit.py)
- Modify: `src/stronghold/conduit.py` (dispatch to reasoning or fallback)

## Evidence References

- [EV-LC-DEEP-05] — model decides delegation, not infrastructure
- [EV-HYPERAGENTS-01] — meta-agent as reasoning orchestrator
- [EV-LG-01] — conditional routing based on state
