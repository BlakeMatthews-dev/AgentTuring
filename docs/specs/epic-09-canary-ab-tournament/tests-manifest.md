# Epic 09: Tests Manifest

| Story | Test path                                    | Test function                                  | Tier     |
|-------|----------------------------------------------|-------------------------------------------------|----------|
| 9.1   | tests/tournament/test_canary_promotion.py    | test_canary_routes_to_candidate                 | critical |
| 9.1   | tests/tournament/test_canary_promotion.py    | test_canary_passes_holdout_promotes             | critical |
| 9.1   | tests/tournament/test_canary_promotion.py    | test_canary_fails_holdout_rollback              | critical |
| 9.1   | tests/tournament/test_canary_promotion.py    | test_canary_cohort_percentage_configurable      | happy    |
| 9.2   | tests/tournament/test_ab_tournament.py       | test_ab_mode_parallel_execution                 | critical |
| 9.2   | tests/tournament/test_ab_tournament.py       | test_ab_winner_auto_promotes                    | critical |
| 9.2   | tests/tournament/test_ab_tournament.py       | test_ab_regression_auto_rollback                | critical |
| 9.2   | tests/tournament/test_ab_tournament.py       | test_tournament_persistence_survives_restart    | happy    |
