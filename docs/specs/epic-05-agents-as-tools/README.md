# Epic 05: Agents-as-Tools

## Summary

Make agent invocation a tool call. Every agent-to-agent call goes through the
same tool-call interface — Sentinel pre-check, trace span, budget attribution,
result return. The tool descriptor is auto-generated from the callee's
CapabilityProfile, surfacing only permitted capabilities with their skill scores
and costs.

## Why Now

Epics 02-04 established the data model (CapabilityProfile), permissions
(agent-call ACLs), and taxonomy (light/heavy). This epic wires the actual
invocation path: when an agent emits a `call_agent` tool call, the runtime
dispatches it through Sentinel, stamps the call chain, and returns the result.

## Depends On

- Epic 04 (Taxonomy)

## Blocks

- Epic 06 (Conduit-as-Reasoning-Agent) — Conduit calls agents as tools
- Epic 11 (Group Chat Patterns) — debate participants call each other as tools

## Ship Gate

Agent A calls Agent B via tool interface. Trace span records caller, callee,
call_chain, tokens charged. Sentinel blocks a denied call.

## Roles Affected

| Role | Impact |
|------|--------|
| Agent author | Agents appear as callable tools to permitted callers |
| Platform operator | Sees agent-to-agent call spans in Phoenix |
| Security auditor | Reviews Sentinel audit log for agent calls |

## Evidence References

- [EV-LC-DEEP-05] — sub-agent spawn as a tool the model calls, not orchestrator plumbing
- [EV-HYPERAGENTS-01] — meta-agent invokes task-agent through a uniform interface

## Files Touched

### New Files
- `src/stronghold/agents/as_tool.py` — agent-tool adapter, descriptor generator, invocation handler
- `tests/agents/as_tools/test_agent_tool_adapter.py`
- `tests/agents/as_tools/test_agent_tool_descriptor.py`
- `tests/agents/as_tools/test_agent_tool_trace.py`

### Modified Files
- `src/stronghold/tools/registry.py` — register agent-tools alongside regular tools
- `src/stronghold/security/sentinel/policy.py` — route agent-tool calls through check_agent_call
- `src/stronghold/agents/base.py` — handle incoming agent-tool calls

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_AGENTS_AS_TOOLS_ENABLED`
- **Canary cohort**: Internal dev org — agent-tools registered but not surfaced to LLM unless flag on
- **Rollback plan**: Disable flag; agents use existing direct dispatch (bypass tool interface)

## Open Questions

None — this epic is well-defined by the preceding four.
