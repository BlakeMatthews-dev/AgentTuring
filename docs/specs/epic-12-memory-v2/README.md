# Epic 12: Memory v2

## Summary

Three memory improvements: (1) self-editing memory tool calls — agents
explicitly write/update their own memories via a tool, not just extracted
learnings; (2) cache-aware routing — co-locate turns on the same provider for
KV cache hits; (3) prompt-cache-hit telemetry so we can measure the cost win.
Temporal knowledge graph and autonoetic side-agent are scaffolding/research-note
only (low priority).

## Why Now

This is a parallel track that depends only on Epic 01 (Eval Substrate) for
validation. The self-editing memory tool is the highest-signal improvement:
agents choosing what to remember produces better memories than extraction-only.

## Depends On

- Epic 01 (Eval Substrate) — eval validation

## Blocks

None directly. Feeds into Epic 13 (meta-level) as another optimizable surface.

## Ship Gate

An agent successfully self-edits a memory via tool call. Cache-hit rate telemetry
emits on Phoenix spans.

## Roles Affected

| Role | Impact |
|------|--------|
| Agent author | Agents can explicitly manage their own memories |
| Platform operator | Views cache-hit rates per provider in Phoenix dashboard |

## Evidence References

- [EV-LETTA-01] — self-editing memory tool calls
- [EV-LETTA-02] — working vs archival memory paging
- [EV-ZEP-01] — temporal knowledge graph with timestamped facts
- [EV-ANTHROPIC-01] — prompt caching / KV reuse

## Files Touched

### New Files
- `src/stronghold/memory/self_edit.py` — self-editing memory tool definition
- `src/stronghold/memory/cache/__init__.py`
- `src/stronghold/memory/cache/routing.py` — cache-aware provider routing
- `src/stronghold/memory/cache/telemetry.py` — cache-hit span attributes
- `tests/memory/v2/test_self_edit.py`
- `tests/memory/v2/test_cache_routing.py`
- `tests/memory/v2/test_cache_telemetry.py`

### Modified Files
- `src/stronghold/agents/base.py` — register self-edit memory tool for agents
- `src/stronghold/tracing/phoenix_backend.py` — add cache-hit attributes to spans
- `src/stronghold/router/selector.py` — integrate cache-awareness into scoring

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_MEMORY_V2_ENABLED`
- **Canary cohort**: Single agent (Mason) for self-edit; all traffic for cache telemetry
- **Rollback plan**: Disable flag; memory extraction-only (current), routing ignores cache

## Open Questions

- OQ-MEM-01: Temporal KG storage backend
- OQ-MEM-02: Can an agent edit another agent's memories, or only its own?
