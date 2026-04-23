# Epic 13: Tests Manifest

| Story | Test path                           | Test function                                     | Tier     |
|-------|-------------------------------------|---------------------------------------------------|----------|
| 13.1  | tests/meta/test_meta_signatures.py  | test_auditor_meta_signature_compiles              | critical |
| 13.1  | tests/meta/test_meta_signatures.py  | test_extractor_meta_signature_compiles            | critical |
| 13.1  | tests/meta/test_meta_signatures.py  | test_promoter_meta_signature_compiles             | critical |
| 13.1  | tests/meta/test_meta_loop.py        | test_meta_updates_versioned_and_gated             | critical |
| 13.2  | tests/meta/test_circuit_breaker.py  | test_breaker_trips_on_excess_mutations            | critical |
| 13.2  | tests/meta/test_circuit_breaker.py  | test_tripped_requires_manual_reenable             | critical |
| 13.2  | tests/meta/test_circuit_breaker.py  | test_audit_log_on_trip                            | happy    |
| 13.2  | tests/meta/test_circuit_breaker.py  | test_below_threshold_no_intervention              | happy    |
