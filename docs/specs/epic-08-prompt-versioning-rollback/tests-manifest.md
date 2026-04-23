# Epic 08: Tests Manifest

| Story | Test path                                 | Test function                               | Tier     |
|-------|-------------------------------------------|---------------------------------------------|----------|
| 8.1   | tests/prompts/versioning/test_store.py    | test_save_creates_version                   | critical |
| 8.1   | tests/prompts/versioning/test_store.py    | test_load_latest_returns_current            | critical |
| 8.1   | tests/prompts/versioning/test_store.py    | test_load_specific_version                  | happy    |
| 8.1   | tests/prompts/versioning/test_store.py    | test_version_history_ordered                | happy    |
| 8.2   | tests/prompts/versioning/test_rollback.py | test_rollback_restores_previous             | critical |
| 8.2   | tests/prompts/versioning/test_rollback.py | test_rollback_triggers_holdout_eval         | critical |
| 8.2   | tests/prompts/versioning/test_rollback.py | test_rollback_nonexistent_version_errors    | happy    |
| 8.3   | tests/prompts/versioning/test_audit.py    | test_audit_log_records_mutation_provenance  | happy    |
| 8.3   | tests/prompts/versioning/test_audit.py    | test_audit_log_records_compilation_source   | happy    |
| 8.3   | tests/prompts/versioning/test_audit.py    | test_audit_log_records_rollback_event       | happy    |
