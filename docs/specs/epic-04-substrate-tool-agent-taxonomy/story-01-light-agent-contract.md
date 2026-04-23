# Story 4.1: Light Agent Contract — No Tools, Agents Only

## User Story

As a **security auditor**, I want light agents structurally prevented from
having tools, so that every side effect in the system is traceable to a heavy
agent with a container and audit trail.

## Background / Motivation

Light agents are orchestration compositions — a prompt + strategy + permission
to call other agents. They touch nothing but other agents; every side effect
originates from a heavy agent. This structural constraint makes the security
boundary trivially verifiable: light agents cannot smuggle side effects through
minimal tool access because they have no tools at all. When they need a tool,
they call an agent with tools. [EV-HYPERAGENTS-01]

## Acceptance Criteria

- AC1: Given an agent.yaml with `kind: light` and `tools: []`, When loaded by
  the factory, Then it registers successfully.
- AC2: Given an agent.yaml with `kind: light` and `tools: [file_read]`, When
  loaded by the factory, Then it raises a validation error ("light agents
  cannot have tools").
- AC3: Given a registered light agent, When it attempts to register a tool at
  runtime, Then the registration is rejected.
- AC4: Given a light agent with `callable_agents: [ranger, scribe]`, When it
  calls ranger, Then the call succeeds via agent-call ACL (Epic 03).
- AC5: Given a light agent, When its CapabilityProfile is generated, Then the
  `tools` dimension is always empty and `agents` dimension reflects its
  callable_agents list.

## Test Mapping (TDD Stubs)

| AC  | Test path                                      | Test function                                    | Tier     |
|-----|------------------------------------------------|--------------------------------------------------|----------|
| AC1 | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_no_tools_registers              | critical |
| AC2 | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_with_tools_rejected             | critical |
| AC3 | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_runtime_tool_registration_fails | critical |
| AC4 | tests/taxonomy/test_light_agent_contract.py    | test_light_agent_calls_agent_succeeds            | happy    |
| AC5 | tests/taxonomy/test_light_agent_contract.py    | test_light_profile_tools_always_empty            | happy    |

## Files to Touch

- New: `src/stronghold/capability/taxonomy.py`
- Modify: `src/stronghold/agents/factory.py` (validate kind + tools constraint)

## Evidence References

- [EV-HYPERAGENTS-01] — meta-agent as orchestration-only, task-agent has tools
