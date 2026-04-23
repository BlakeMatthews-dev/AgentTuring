# Epic 12: Tests Manifest

| Story | Test path                              | Test function                                | Tier     |
|-------|----------------------------------------|----------------------------------------------|----------|
| 12.1  | tests/memory/v2/test_self_edit.py      | test_agent_writes_memory_via_tool            | critical |
| 12.1  | tests/memory/v2/test_self_edit.py      | test_agent_updates_existing_memory           | happy    |
| 12.1  | tests/memory/v2/test_self_edit.py      | test_agent_cannot_edit_other_agent_memory    | critical |
| 12.1  | tests/memory/v2/test_self_edit.py      | test_self_edit_scoped_to_org                 | critical |
| 12.2  | tests/memory/v2/test_cache_routing.py  | test_cache_aware_prefers_same_provider       | happy    |
| 12.2  | tests/memory/v2/test_cache_routing.py  | test_cache_score_factor_in_routing           | happy    |
| 12.3  | tests/memory/v2/test_cache_telemetry.py| test_cache_hit_rate_emitted_on_span          | happy    |
| 12.3  | tests/memory/v2/test_cache_telemetry.py| test_cache_miss_emitted_on_span              | happy    |
