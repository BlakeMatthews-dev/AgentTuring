# Epic 10: Tests Manifest

| Story | Test path                          | Test function                                 | Tier     |
|-------|------------------------------------|-----------------------------------------------|----------|
| 10.1  | tests/routing/test_switching.py    | test_switch_on_cost_threshold                 | critical |
| 10.1  | tests/routing/test_switching.py    | test_switch_on_latency_spike                  | happy    |
| 10.1  | tests/routing/test_switching.py    | test_conversation_continuity_after_switch     | critical |
| 10.1  | tests/routing/test_switching.py    | test_trace_records_switch_reason              | happy    |
| 10.1  | tests/routing/test_switching.py    | test_downshift_to_cheaper_for_simple_followup | happy    |
| 10.1  | tests/routing/test_switching.py    | test_upshift_for_complex_reasoning            | happy    |
