# Epic 04: Tests Manifest

| Story | Test path                                      | Test function                                    | Tier     |
|-------|-------------------------------------------------|--------------------------------------------------|----------|
| 4.1   | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_no_tools_registers              | critical |
| 4.1   | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_with_tools_rejected             | critical |
| 4.1   | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_runtime_tool_registration_fails | critical |
| 4.1   | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_calls_agent_succeeds            | happy    |
| 4.1   | tests/taxonomy/test_light_agent_contract.py    | test_light_profile_tools_always_empty            | happy    |
| 4.2   | tests/taxonomy/test_taxonomy.py                | test_heavy_agent_registers_with_tools            | critical |
| 4.2   | tests/taxonomy/test_taxonomy.py                | test_heavy_cost_vector_includes_standing         | happy    |
| 4.2   | tests/taxonomy/test_taxonomy.py                | test_missing_kind_defaults_heavy                 | critical |
| 4.3   | tests/taxonomy/test_taxonomy.py                | test_light_agent_llm_no_permission_check         | critical |
| 4.3   | tests/taxonomy/test_taxonomy.py                | test_substrate_utility_no_permission_check        | happy    |
| 4.3   | tests/taxonomy/test_taxonomy.py                | test_impure_utility_rejected_at_registration     | critical |
| 4.3   | tests/taxonomy/test_taxonomy.py                | test_http_utility_rejected_as_substrate          | happy    |
