# Epic 06: Tests Manifest

| Story | Test path                                | Test function                                  | Tier     |
|-------|------------------------------------------|-------------------------------------------------|----------|
| 6.1   | tests/conduit/test_reasoning_loop.py     | test_reasoning_emits_call_agent                 | critical |
| 6.1   | tests/conduit/test_reasoning_loop.py     | test_profiles_logged_in_trace                   | happy    |
| 6.1   | tests/conduit/test_reasoning_loop.py     | test_routes_to_higher_skill_agent               | critical |
| 6.1   | tests/conduit/test_reasoning_loop.py     | test_max_turns_returns_best_response            | critical |
| 6.1   | tests/conduit/test_reasoning_fallback.py | test_flag_off_uses_heuristic_router             | critical |
