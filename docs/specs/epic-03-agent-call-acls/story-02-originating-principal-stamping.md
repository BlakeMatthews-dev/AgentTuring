# Story 3.2: Originating-Principal Stamping on Call Chains

## User Story

As a **security auditor**, I want every sub-agent call to carry the originating
caller's identity through the full chain, so that transitive privilege
escalation is blocked even when intermediate agents have broader permissions.

## Background / Motivation

If Ranger can call Scribe and Scribe can call Mason, Ranger could transitively
reach Mason's code_gen capability — violating the intent of Ranger's permission
boundary. Originating-principal stamping ensures Mason checks "who started this
chain?" not just "who called me directly?" The Hyperagents paper
[EV-HYPERAGENTS-01] demonstrates meta-agent → task-agent chains that need
governance at every hop.

## Acceptance Criteria

- AC1: Given AuthContext with `call_chain: []`, When agent A calls agent B,
  Then B's AuthContext has `call_chain: [A]` and `originating_principal: user`.
- AC2: Given AuthContext with `call_chain: [A]`, When agent B calls agent C,
  Then C's AuthContext has `call_chain: [A, B]` and `originating_principal: user`
  (unchanged).
- AC3: Given agent C with `callable_agents` that excludes the originating
  principal's agent scope, When C receives a call where `call_chain[0]` is a
  restricted agent, Then the call is denied.
- AC4: Given a call chain `[A, B, A]` (cycle), When detected, Then the call is
  denied with a cycle-detection error.

## Test Mapping (TDD Stubs)

| AC  | Test path                                        | Test function                                    | Tier     |
|-----|--------------------------------------------------|--------------------------------------------------|----------|
| AC1 | tests/security/test_agent_acl_transitive.py      | test_single_hop_stamps_caller                    | critical |
| AC2 | tests/security/test_agent_acl_transitive.py      | test_multi_hop_preserves_originating_principal   | critical |
| AC3 | tests/security/test_agent_acl_transitive.py      | test_transitive_escalation_blocked               | critical |
| AC4 | tests/security/test_agent_acl_transitive.py      | test_cycle_detection_denies_call                 | critical |

## Files to Touch

- New: `src/stronghold/security/agent_acl.py` (call-chain logic, cycle detection)
- Modify: `src/stronghold/types/auth.py` (add call_chain, originating_principal)

## Evidence References

- [EV-HYPERAGENTS-01] — meta-agent / task-agent chains need governance at every hop
