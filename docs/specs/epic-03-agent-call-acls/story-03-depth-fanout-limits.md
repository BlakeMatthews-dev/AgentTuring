# Story 3.3: Depth and Fanout Limits on Recursive Calls

## User Story

As a **platform operator**, I want configurable depth and fanout limits on
recursive agent calls, so that a malformed prompt cannot fan out an unbounded
agent tree and exhaust quotas.

## Background / Motivation

"Ranger can call sub-Ranger" is the right default for recursive decomposition,
but without bounds a malformed prompt can create exponential call trees. Simple
`max_depth` and `max_fanout` per agent in the PermissionTable prevents this
while preserving composability.

## Acceptance Criteria

- AC1: Given `max_depth: 3` for an agent, When a call chain reaches depth 3,
  Then the next call attempt is denied with a depth-limit error.
- AC2: Given `max_fanout: 5` for an agent, When an agent attempts 6 parallel
  sub-agent calls, Then the 6th is denied with a fanout-limit error.
- AC3: Given no explicit limits configured, When an agent makes calls, Then
  system defaults apply (depth=3, fanout=5).
- AC4: Given a denied call due to limits, When the denial is logged, Then the
  audit entry includes depth, fanout, call_chain, and the limit that triggered.

## Test Mapping (TDD Stubs)

| AC  | Test path                            | Test function                           | Tier     |
|-----|--------------------------------------|-----------------------------------------|----------|
| AC1 | tests/security/test_agent_acl.py     | test_depth_limit_blocks_at_max          | critical |
| AC2 | tests/security/test_agent_acl.py     | test_fanout_limit_blocks_excess         | critical |
| AC3 | tests/security/test_agent_acl.py     | test_default_limits_applied             | happy    |
| AC4 | tests/security/test_agent_acl.py     | test_denial_audit_includes_limit_info   | happy    |

## Files to Touch

- Modify: `src/stronghold/security/agent_acl.py` (depth/fanout enforcement)
- Modify: `src/stronghold/security/sentinel/policy.py` (add max_depth, max_fanout to PermissionTable)

## Evidence References

- [EV-HYPERAGENTS-01] — bounded recursion in meta-agent systems
