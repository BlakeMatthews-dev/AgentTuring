# Story 5.2: Agent-Tool Descriptor from CapabilityProfile

## User Story

As an **agent author**, I want the tool descriptor for a callable agent to be
auto-generated from its CapabilityProfile, so that the calling agent sees only
permitted capabilities with their skill scores and costs — and blocked
capabilities are invisible.

## Background / Motivation

The reasoning agent (Conduit or any delegating agent) needs to see the (skill,
cost) tradeoffs for each callable agent. The tool descriptor surfaces only
ALLOWED capabilities — blocked ones don't appear in context (no temptation, no
prompt-injection vector). Skill and cost are included in the description so the
LLM can make economic decisions natively.

## Acceptance Criteria

- AC1: Given agent B with capabilities `{write_text: {perm: ALLOWED, skill: 8,
  cost: 5}, code_gen: {perm: BLOCKED}}`, When the descriptor is generated for
  caller A, Then `code_gen` is absent from the tool description.
- AC2: Given agent B's descriptor, When the LLM reads it, Then it includes
  `write_text (skill: 8, cost: 5)` in the function description.
- AC3: Given agent B has intent-conditional skills `{write_text: {summary: 4,
  report: 8}}`, When the descriptor is generated, Then both intent-level scores
  are included.
- AC4: Given caller A has `callable_agents: [B, C]`, When tools are listed for
  A, Then both B and C appear as callable tools alongside A's regular tools.

## Test Mapping (TDD Stubs)

| AC  | Test path                                            | Test function                                    | Tier     |
|-----|------------------------------------------------------|--------------------------------------------------|----------|
| AC1 | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_blocked_capability_absent_from_descriptor   | critical |
| AC2 | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_skill_cost_in_description                   | happy    |
| AC3 | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_intent_conditional_scores_included          | happy    |
| AC4 | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_multiple_callable_agents_listed             | happy    |

## Files to Touch

- Modify: `src/stronghold/agents/as_tool.py` (descriptor generation from CapabilityProfile)

## Evidence References

- [EV-HYPERAGENTS-02] — per-capability scoring surfaces to decision-maker
- [EV-FRUGAL-01] — cost-aware routing needs visible cost in context
