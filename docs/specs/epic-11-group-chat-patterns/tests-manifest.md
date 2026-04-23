# Epic 11: Tests Manifest

| Story | Test path                                    | Test function                                | Tier     |
|-------|----------------------------------------------|----------------------------------------------|----------|
| 11.1  | tests/agents/debate/test_debate_protocol.py  | test_debate_round_produces_critique          | critical |
| 11.1  | tests/agents/debate/test_debate_protocol.py  | test_debate_converges_within_max_rounds      | critical |
| 11.1  | tests/agents/debate/test_debate_protocol.py  | test_debate_participants_call_via_tool       | happy    |
| 11.2  | tests/agents/debate/test_scribe_debate.py    | test_scribe_debate_outperforms_single_pass   | perf     |
| 11.2  | tests/agents/debate/test_scribe_debate.py    | test_scribe_debate_preserves_token_budget    | happy    |
| 11.3  | tests/agents/debate/test_debate_protocol.py  | test_pattern_registry_lists_available        | happy    |
| 11.3  | tests/agents/debate/test_debate_protocol.py  | test_conduit_selects_pattern_for_intent      | happy    |
