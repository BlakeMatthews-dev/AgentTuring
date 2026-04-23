# Story 3.1: Add `agents` Field to PermissionTable

## User Story

As a **security auditor**, I want agent-to-agent call permissions declared
alongside tool permissions, so that I can review the full action surface of any
agent in one place.

## Background / Motivation

Today PermissionTable only has tool permissions. If sub-agents become tools
(Epic 05), the permission check must be uniform: "is this target in the caller's
agents/tools list?" Adding the `agents` field now prepares the schema before
the invocation path is wired.

## Acceptance Criteria

- AC1: Given a PermissionTable with `agents: [scribe, ranger]`, When
  `check_agent_call(caller=ranger, target=scribe)` is called, Then it returns
  allowed.
- AC2: Given a PermissionTable with `agents: [scribe, ranger]`, When
  `check_agent_call(caller=ranger, target=mason)` is called, Then it returns
  denied.
- AC3: Given an agent.yaml with `callable_agents: [ranger, scribe]`, When
  loaded by the factory, Then the PermissionTable for that agent includes those
  entries.
- AC4: Given a PermissionTable without an `agents` field (legacy), When
  loaded, Then it defaults to empty list (deny all agent calls).

## Test Mapping (TDD Stubs)

| AC  | Test path                              | Test function                                 | Tier     |
|-----|----------------------------------------|-----------------------------------------------|----------|
| AC1 | tests/security/test_agent_acl.py       | test_allowed_agent_call                       | critical |
| AC2 | tests/security/test_agent_acl.py       | test_denied_agent_call                        | critical |
| AC3 | tests/security/test_agent_acl.py       | test_yaml_callable_agents_loaded              | happy    |
| AC4 | tests/security/test_agent_acl.py       | test_legacy_no_agents_field_denies_all        | critical |

## Files to Touch

- Modify: `src/stronghold/security/sentinel/policy.py` (add agents field, check_agent_call)
- Modify: `src/stronghold/agents/factory.py` (parse callable_agents from YAML)

## Evidence References

- [EV-OH-01] — permission modes extended to agent invocation
