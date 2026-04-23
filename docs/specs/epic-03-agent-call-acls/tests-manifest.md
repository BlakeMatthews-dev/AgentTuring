# Epic 03: Tests Manifest

| Story | Test path                                        | Test function                                    | Tier     |
|-------|--------------------------------------------------|--------------------------------------------------|----------|
| 3.1   | tests/security/test_agent_acl.py                 | test_allowed_agent_call                          | critical |
| 3.1   | tests/security/test_agent_acl.py                 | test_denied_agent_call                           | critical |
| 3.1   | tests/security/test_agent_acl.py                 | test_yaml_callable_agents_loaded                 | happy    |
| 3.1   | tests/security/test_agent_acl.py                 | test_legacy_no_agents_field_denies_all           | critical |
| 3.2   | tests/security/test_agent_acl_transitive.py      | test_single_hop_stamps_caller                    | critical |
| 3.2   | tests/security/test_agent_acl_transitive.py      | test_multi_hop_preserves_originating_principal   | critical |
| 3.2   | tests/security/test_agent_acl_transitive.py      | test_transitive_escalation_blocked               | critical |
| 3.2   | tests/security/test_agent_acl_transitive.py      | test_cycle_detection_denies_call                 | critical |
| 3.3   | tests/security/test_agent_acl.py                 | test_depth_limit_blocks_at_max                   | critical |
| 3.3   | tests/security/test_agent_acl.py                 | test_fanout_limit_blocks_excess                  | critical |
| 3.3   | tests/security/test_agent_acl.py                 | test_default_limits_applied                      | happy    |
| 3.3   | tests/security/test_agent_acl.py                 | test_denial_audit_includes_limit_info            | happy    |
