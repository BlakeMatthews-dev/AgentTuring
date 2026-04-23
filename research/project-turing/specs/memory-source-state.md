# Spec 34 — Memory source-state resolution

*`source_kind = "memory"` currently returns 0.5 unconditionally in the sketch. Wire it to the memory's actual weight. Closes F30.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [activation-graph.md](./activation-graph.md), [persistence.md](./persistence.md).
**Depended on by:** [operator-review-gate.md](./operator-review-gate.md) (digest surfaces "heaviest self-contributors"), [facet-drift-budget.md](./facet-drift-budget.md) (REGRET vs OBSERVATION carry different weight).

---

## Current state

`self_activation.source_state(...)` in the sketch returns `0.5` for `source_kind == "memory"` with a TODO comment. This breaks the design invariant that REGRET memories (weight ≥ 0.6) should contribute more heavily than OBSERVATION memories (< 0.3) to activation — in the current state, they contribute identically.

## Target

Resolve `source_kind == "memory"` by looking up the memory row from the episodic and durable memory tables and returning `clamp(memory.weight, 0.0, 1.0)`. Dangling memory IDs fall through to the existing "weight-0 skip" path (spec 25 AC-25.23).

## Acceptance criteria

### Resolution

- **AC-34.1.** `source_state(repo, source_id, "memory", ctx)` reads the episodic memory repo with `repo.memory_repo.get(source_id)` and returns `clamp(mem.weight, 0.0, 1.0)`. Test with a known OBSERVATION (weight ≈ 0.2) and a known REGRET (weight ≥ 0.6); the two activations differ.
- **AC-34.2.** Missing memory ID — neither in `episodic_memory` nor `durable_memory` — raises `KeyError` at source_state, handled by the existing `active_now` loop as "skip this contributor." Test with an unknown id; activation is unchanged from zero-contributor baseline.
- **AC-34.3.** Deleted (soft) memories (`deleted = 1` in episodic) are treated as dangling — the KeyError-skip path fires. Test.

### Wiring

- **AC-34.4.** `ActivationContext` grows an optional `memory_repo: MemoryRepo | None` field. `source_state` uses it; when None (older callers), the legacy 0.5 behavior is preserved behind a `LegacyMemoryStub` flag with a DeprecationWarning. Default for new code is wired. Test both paths.
- **AC-34.5.** The existing `Repo` class (memory) gains a `get(memory_id) -> EpisodicMemory` method that transparently searches both episodic and durable tables. O(1) with PK lookup. Test for each table.

### Activation consequence

- **AC-34.6.** Integration test: two facets each with a `source_kind="memory"` contributor of weight=+0.5; one source is an OBSERVATION (stored weight 0.2), the other a REGRET (stored weight 0.8). `active_now` for the REGRET-backed facet is strictly higher. Close the F30 regression via this test.

### Performance

- **AC-34.7.** `source_state` for memory adds one PK lookup per contributor per `active_now`. Budget: ≤ 0.5ms per facet with 8 contributors. Benchmark test.

## Implementation

```python
# self_activation.py

def source_state(repo, source_id, source_kind, ctx):
    ...
    if source_kind == "memory":
        if ctx.memory_repo is None:
            return 0.5  # legacy stub, deprecated
        try:
            mem = ctx.memory_repo.get(source_id)
        except KeyError:
            raise  # skipped by active_now loop
        if mem.deleted:
            raise KeyError(source_id)
        return max(0.0, min(1.0, mem.weight))
    ...
```

```python
# repo.py — union read path
def get(self, memory_id: str) -> EpisodicMemory:
    row = self._conn.execute(
        "SELECT * FROM episodic_memory WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        row = self._conn.execute(
            "SELECT * FROM durable_memory WHERE memory_id = ?", (memory_id,)
        ).fetchone()
    if row is None:
        raise KeyError(memory_id)
    return _row_to_memory(row)
```

## Open questions

- **Q34.1.** Legacy 0.5 stub kept behind a deprecation warning or removed outright? The wired version is small enough that keeping a legacy path just hides future breakage. Lean toward removing once all callers migrate (same PR).
- **Q34.2.** Deleted memories treated as dangling. Alternative: treated with weight 0 but not skipped (i.e. still counted in contributor sum for stats). Dangling-skip is simpler.
- **Q34.3.** Union read across `episodic_memory` and `durable_memory` does two lookups on cache miss. A view `memory_all` could collapse them. Not required for correctness; worth it for perf if the benchmark fails AC-34.7.
