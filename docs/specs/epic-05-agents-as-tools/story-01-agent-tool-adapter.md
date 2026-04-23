# Story 5.1: Agent-Tool Adapter

## User Story

As an **agent author**, I want any registered agent to be callable as a tool by
permitted agents, so that delegation happens through the same interface as tool
calls — with Sentinel checks, trace spans, and budget attribution.

## Background / Motivation

LangChain's deepagents [EV-LC-DEEP-05] makes sub-agent spawn a tool the model
calls. This collapses the distinction between "use a tool" and "ask another
agent" into one primitive: emit a tool call, the runtime handles dispatch. The
adapter generates a tool definition from the callee's CapabilityProfile and
handles invocation, including call-chain stamping (Epic 03) and context
isolation.

## Acceptance Criteria

- AC1: Given agent B registered as a tool, When agent A emits
  `call_agent(agent="B", task="summarize this")`, Then agent B receives the
  task and returns a response.
- AC2: Given the call, When Sentinel is checked, Then `check_agent_call` is
  invoked with caller=A, target=B, call_chain from AuthContext.
- AC3: Given a successful call, When the trace is recorded, Then a child span
  is emitted with attributes: caller, callee, call_chain, tokens_in,
  tokens_out, duration_ms.
- AC4: Given agent B's response, When budget is attributed, Then tokens are
  charged to BOTH agent A's budget AND the originating user's budget.
- AC5: Given the feature flag is disabled, When agent A tries to call agent B
  as a tool, Then the tool is not registered (invisible to the LLM).

## Test Mapping (TDD Stubs)

| AC  | Test path                                        | Test function                                | Tier     |
|-----|--------------------------------------------------|----------------------------------------------|----------|
| AC1 | tests/agents/as_tools/test_agent_tool_adapter.py | test_call_agent_returns_response             | critical |
| AC2 | tests/agents/as_tools/test_agent_tool_adapter.py | test_sentinel_check_invoked_on_call          | critical |
| AC3 | tests/agents/as_tools/test_agent_tool_trace.py   | test_trace_span_emitted_on_agent_call        | happy    |
| AC4 | tests/agents/as_tools/test_agent_tool_adapter.py | test_dual_budget_attribution                 | critical |
| AC5 | tests/agents/as_tools/test_agent_tool_adapter.py | test_flag_disabled_tool_not_registered        | happy    |

## Files to Touch

- New: `src/stronghold/agents/as_tool.py`
- Modify: `src/stronghold/tools/registry.py` (register agent-tools)

## Evidence References

- [EV-LC-DEEP-05] — sub-agent spawn as tool call
- [EV-HYPERAGENTS-01] — uniform invocation interface for meta/task agents
