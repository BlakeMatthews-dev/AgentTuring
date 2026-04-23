# Epic 03: Agent-Call ACLs

## Summary

Extend the PermissionTable so agents can call other agents as a permissioned
action — governed by Sentinel the same way tool calls are. Introduce originating-
principal stamping on call chains for transitive escalation prevention, depth/
fanout limits for recursive calls, and dual budget attribution (charge to both
calling agent and originating user).

## Why Now

Epic 02 (CapabilityProfile) defines what agents *can* do. This epic defines
what agents *can call*. Agent-call permissions must exist before agents-as-tools
(Epic 05) wires the actual invocation path.

## Depends On

- Epic 02 (CapabilityProfile) — permission is one dimension of the profile

## Blocks

- Epic 04 (Taxonomy) — light agents are defined by "tools=[], agents=[...]"
- Epic 05 (Agents-as-Tools) — tool adapter needs permission checks

## Ship Gate

Sentinel blocks a transitive escalation attempt (Scribe → Ranger → Mason) in
the test suite. Call-chain depth limit triggers at configured maximum.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Configures agent-call ACLs per agent |
| Agent author | Declares which agents their agent can call |
| Security auditor | Reviews call-chain audit logs for escalation attempts |
| Tenant admin | Views per-agent delegation permissions |

## Evidence References

- [EV-HYPERAGENTS-01] — meta-agent calling task-agent needs governance
- [EV-OH-01] — permission modes for tool invocation (extended to agent invocation)

## Files Touched

### New Files
- `src/stronghold/security/agent_acl.py` — call-chain, depth/fanout checks
- `tests/security/test_agent_acl.py`
- `tests/security/test_agent_acl_transitive.py`

### Modified Files
- `src/stronghold/security/sentinel/policy.py` — add `agents: [...]` to PermissionTable, add `check_agent_call()`
- `src/stronghold/types/auth.py` — add `call_chain: list[str]` to AuthContext
- `agents/*/agent.yaml` — add `callable_agents:` field
- `tests/fakes.py` — extend FakeAuthProvider to support call_chain

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_AGENT_CALL_ACLS_ENABLED`
- **Canary cohort**: Internal dev org
- **Rollback plan**: Disable flag; agent calls skip ACL check (open-by-default, same as today)

## Open Questions

- OQ-ACL-01: Principal propagation across async boundaries
- OQ-ACL-02: Default depth limit
