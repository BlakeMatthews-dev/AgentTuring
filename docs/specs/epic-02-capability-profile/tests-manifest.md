# Epic 02: Tests Manifest

| Story | Test path                                | Test function                                    | Tier     |
|-------|------------------------------------------|--------------------------------------------------|----------|
| 2.1   | tests/capability/test_profile_schema.py  | test_full_profile_validates                      | critical |
| 2.1   | tests/capability/test_profile_schema.py  | test_missing_skill_raises_validation_error       | critical |
| 2.1   | tests/capability/test_profile_schema.py  | test_intent_conditional_skill_lookup             | critical |
| 2.1   | tests/capability/test_profile_schema.py  | test_cost_vector_includes_standing_resources     | happy    |
| 2.1   | tests/capability/test_profile_schema.py  | test_blocked_capability_omitted_from_visible     | critical |
| 2.2   | tests/capability/test_updater.py         | test_ema_updates_skill_from_outcome              | critical |
| 2.2   | tests/capability/test_updater.py         | test_no_outcomes_preserves_prior                 | happy    |
| 2.2   | tests/capability/test_updater.py         | test_convergence_after_many_outcomes             | happy    |
| 2.2   | tests/capability/test_updater.py         | test_per_org_isolation                           | critical |
