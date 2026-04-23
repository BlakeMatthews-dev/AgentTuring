# Epic 07: Tests Manifest

| Story | Test path                       | Test function                               | Tier     |
|-------|---------------------------------|---------------------------------------------|----------|
| 7.1   | tests/dspy/test_signatures.py   | test_mason_planner_signature_shape          | critical |
| 7.1   | tests/dspy/test_signatures.py   | test_auditor_rubric_signature_shape         | critical |
| 7.1   | tests/dspy/test_signatures.py   | test_conduit_routing_signature_shape        | critical |
| 7.1   | tests/dspy/test_signatures.py   | test_compiled_signature_is_drop_in          | happy    |
| 7.2   | tests/dspy/test_training.py     | test_auditor_outcome_to_training_example    | critical |
| 7.2   | tests/dspy/test_training.py     | test_high_score_labeled_positive            | happy    |
| 7.2   | tests/dspy/test_training.py     | test_low_score_labeled_negative             | happy    |
| 7.2   | tests/dspy/test_training.py     | test_behavioral_tag_included_in_example     | happy    |
