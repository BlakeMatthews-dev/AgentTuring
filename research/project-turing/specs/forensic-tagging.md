# Spec 39 — Forensic tagging on self-writes (G17)

*Every self-model write carries `request_hash` and `perception_tool_call_id` so the full provenance of any row is reconstructible after the fact. Closes F1 (partial), F18 (partial).*

**Depends on:** [memory-mirroring.md](./memory-mirroring.md), [self-tool-registry.md](./self-tool-registry.md), [conduit-runtime.md](./conduit-runtime.md).
**Depended on by:** [operator-review-gate.md](./operator-review-gate.md) (digest filters by request).

---

## Current state

Self-model writes do not carry provenance tying them to the request that produced them. Auditing "which routing episode caused the self to note this passion?" requires guesswork.

## Target

Two `ContextVar`s — `_request_hash_var` and `_perception_tool_call_id_var` — set at request pipeline boundaries. The memory-mirroring bridge (spec 32) reads them and stamps every mirror memory's `context` dict. Out-of-band writes (migrations, manual fixes) carry `context.provenance = "out_of_band"`.

## Acceptance criteria

### Context binding

- **AC-39.1.** `_request_hash_var: ContextVar[str | None]` and `_perception_tool_call_id_var: ContextVar[str | None]` are defined in `self_memory_bridge.py` (or a `self_forensics.py` sibling). Default `None`. Test.
- **AC-39.2.** `with request_scope(request_hash):` context manager sets and unsets `_request_hash_var`. Nested scopes raise (one request at a time per process). Test.
- **AC-39.3.** `with tool_call_scope(perception_tool_call_id):` likewise. Nestable (multiple tool calls per request). Test.

### Stamping

- **AC-39.4.** `memory_bridge.mirror_*(...)` reads both vars and writes `context.request_hash`, `context.perception_tool_call_id` when set. Test with context bound; test without.
- **AC-39.5.** Self-model row `context` dicts also carry these fields when the write is in a request scope. Specifically:
  - `note_*` writes stamp their contributor-edge rows (if any).
  - `write_self_todo` stamps the todo row.
  - `record_personality_claim` stamps the OPINION memory via the bridge.
  - `write_contributor` stamps the contributor row's `rationale` as `"{rationale} [req:{hash[:8]}]"`.
  Test per shape.

### Out-of-band writes

- **AC-39.6.** A write without any active scope adds `context.provenance = "out_of_band"` to the mirror memory. Test.
- **AC-39.7.** A direct repo insert bypassing the tool surface is detected via a schema-level trigger that raises if neither `request_hash` nor `provenance=out_of_band` is present in the memory's `context`. Test with a direct insert missing both.

### Indexing

- **AC-39.8.** Add an index on `json_extract(context, '$.request_hash')` over both `episodic_memory` and `durable_memory`. Audit query `SELECT * FROM episodic_memory WHERE json_extract(context, '$.request_hash') = ?` uses the index. Test with EXPLAIN QUERY PLAN.
- **AC-39.9.** `stronghold self forensics --request <hash>` emits all memories and self-model rows tied to that request, sorted by `created_at`. Test.

### Pipeline integration

- **AC-39.10.** Spec 44's request pipeline computes `request_hash = sha256(method + path + body)[:16]` once at step 1, binds via `request_scope`, releases at step 8. Test.
- **AC-39.11.** Each perception/observation tool-call execution sets `tool_call_scope(uuid4().hex)` for the duration of the handler. Test.

### Edge cases

- **AC-39.12.** Concurrent requests on the same process (if ever allowed — spec 30 serializes) cannot share `ContextVar` state because `ContextVar`s are per-async-task. Test.
- **AC-39.13.** A tool call that forks a background task inherits the parent's vars until reassigned (`contextvars.copy_context()` semantics). Document this.
- **AC-39.14.** `request_hash` truncated to 16 hex chars: 64 bits of entropy, sufficient to avoid collisions across years of operation at low request volumes. Documented.

## Implementation

```python
# self_forensics.py

_request_hash_var: ContextVar[str | None] = ContextVar("request_hash", default=None)
_perception_tool_call_id_var: ContextVar[str | None] = ContextVar(
    "perception_tool_call_id", default=None,
)


@contextmanager
def request_scope(request_hash: str) -> Iterator[None]:
    if _request_hash_var.get() is not None:
        raise RuntimeError("nested request_scope")
    token = _request_hash_var.set(request_hash)
    try:
        yield
    finally:
        _request_hash_var.reset(token)


@contextmanager
def tool_call_scope(tool_call_id: str) -> Iterator[None]:
    token = _perception_tool_call_id_var.set(tool_call_id)
    try:
        yield
    finally:
        _perception_tool_call_id_var.reset(token)
```

Memory-bridge augmentation:
```python
def _augment_context(self_id: str, ctx: dict | None) -> dict:
    out = dict(ctx or {})
    out["self_id"] = self_id
    out["mirror"] = True
    rh = _request_hash_var.get(default=None)
    if rh is not None:
        out["request_hash"] = rh
    tcid = _perception_tool_call_id_var.get(default=None)
    if tcid is not None:
        out["perception_tool_call_id"] = tcid
    if "request_hash" not in out and "provenance" not in out:
        out["provenance"] = "out_of_band"
    return out
```

Schema trigger (SQLite):
```sql
CREATE TRIGGER mem_require_provenance
    BEFORE INSERT ON episodic_memory
    WHEN json_extract(NEW.context, '$.request_hash') IS NULL
     AND json_extract(NEW.context, '$.provenance') IS NULL
BEGIN
    SELECT RAISE(ABORT, 'memory insert missing provenance (request_hash or provenance)');
END;
```

## Open questions

- **Q39.1.** The schema trigger applies to all episodic memory, not just self-model mirrors. Existing write paths (daydream, etc.) need to set `provenance` or `request_hash` too. Migration audit required; may need a "legacy" provenance value for older rows.
- **Q39.2.** 64 bits of hash is tight at web scale. Research scale is fine. For any production port, widen to 128 bits.
- **Q39.3.** Nested request scopes are rejected. The alternative — allowing nested with stack semantics — supports batch operations but complicates audit. Current spec's "one request at a time" matches spec 30 §30.6.
