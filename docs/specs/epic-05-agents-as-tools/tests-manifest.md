# Epic 05: Tests Manifest

| Story | Test path                                            | Test function                                    | Tier     |
|-------|------------------------------------------------------|--------------------------------------------------|----------|
| 5.1   | tests/agents/as_tools/test_agent_tool_adapter.py     | test_call_agent_returns_response                 | critical |
| 5.1   | tests/agents/as_tools/test_agent_tool_adapter.py     | test_sentinel_check_invoked_on_call              | critical |
| 5.1   | tests/agents/as_tools/test_agent_tool_trace.py       | test_trace_span_emitted_on_agent_call            | happy    |
| 5.1   | tests/agents/as_tools/test_agent_tool_adapter.py     | test_dual_budget_attribution                     | critical |
| 5.1   | tests/agents/as_tools/test_agent_tool_adapter.py     | test_flag_disabled_tool_not_registered            | happy    |
| 5.2   | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_blocked_capability_absent_from_descriptor   | critical |
| 5.2   | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_skill_cost_in_description                   | happy    |
| 5.2   | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_intent_conditional_scores_included          | happy    |
| 5.2   | tests/agents/as_tools/test_agent_tool_descriptor.py  | test_multiple_callable_agents_listed             | happy    |
