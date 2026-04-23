# Epic 01: Tests Manifest

All test paths introduced by this epic.

| Story | Test path                               | Test function                              | Tier     |
|-------|-----------------------------------------|--------------------------------------------|----------|
| 1.1   | tests/eval/test_tags.py                 | test_span_includes_behavior_tag            | critical |
| 1.1   | tests/eval/test_tags.py                 | test_tag_selected_from_registry            | happy    |
| 1.1   | tests/eval/test_tags.py                 | test_unclassifiable_defaults_unclassified  | critical |
| 1.1   | tests/eval/test_tags.py                 | test_flag_disabled_no_tag_added            | happy    |
| 1.2   | tests/eval/test_dataset.py              | test_split_produces_disjoint_sets          | critical |
| 1.2   | tests/eval/test_dataset.py              | test_optimization_set_excludes_holdout     | critical |
| 1.2   | tests/eval/test_dataset.py              | test_holdout_set_excludes_optimization     | critical |
| 1.2   | tests/eval/test_dataset.py              | test_stratified_split_preserves_tag_dist   | happy    |
| 1.2   | tests/eval/test_dataset.py              | test_split_deterministic_with_seed         | happy    |
| 1.3   | tests/eval/test_swebench_adapter.py     | test_load_instance_produces_eval_sample    | happy    |
| 1.3   | tests/eval/test_swebench_adapter.py     | test_runner_dispatches_to_coding_agent     | happy    |
| 1.3   | tests/eval/test_swebench_adapter.py     | test_scorer_pass_on_correct_patch          | happy    |
| 1.3   | tests/eval/test_swebench_adapter.py     | test_batch_aggregates_pass_at_1            | happy    |
| 1.4   | tests/eval/test_inspect_adapter.py      | test_inspect_task_to_eval_sample           | happy    |
| 1.4   | tests/eval/test_inspect_adapter.py      | test_agent_as_inspect_solver               | happy    |
| 1.4   | tests/eval/test_inspect_adapter.py      | test_inspect_scorer_to_eval_report         | happy    |
| 1.4   | tests/eval/test_inspect_adapter.py      | test_sample_isolation                      | happy    |
| 1.5   | tests/eval/test_report.py               | test_report_includes_required_fields       | critical |
| 1.5   | tests/eval/test_report.py               | test_report_delta_computation              | happy    |
| 1.5   | tests/eval/test_report.py               | test_report_serialization_roundtrip        | critical |
| 1.5   | tests/eval/test_report.py               | test_report_flags_regression               | happy    |
