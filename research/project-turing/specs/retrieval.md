# Spec 6 — Retrieval semantics

*How durable memories are retrieved, how source provenance filters the view, and how the context builder protects durable tiers from budget-pressure starvation.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md).
**Depended on by:** [daydreaming.md](./daydreaming.md).

---

## Current state

- Context builder retrieves by scope, weight, and relevance. No tier-aware reservation.
- No source typing, so no source-filtered views.
- No explicit lineage walk — a memory that has been superseded still reads as current.

## Target

Three retrieval behaviors, all enforced at the context-builder / repository boundary.

## Acceptance criteria

- **AC-6.1.** `DURABLE_MIN_TOKENS` (default 800) is reserved for durable-tier retrievals before any non-durable retrievals are selected. Property test over random budgets asserts the reserved quota is honored whenever at least one durable memory matches.
- **AC-6.2.** If durable-tier relevance-matches total fewer than `DURABLE_MIN_TOKENS`, the unused remainder is released to other tiers. No quota is left empty if the rest of the context window needs it. Test.
- **AC-6.3.** A retrieval request with `source_filter = {SourceKind.I_DID}` returns only I_DID memories. Memories with other sources are excluded even if they match relevance. Test over mixed-provenance fixture.
- **AC-6.4.** The default retrieval source filter for routing decisions is `{SourceKind.I_DID}`. Prospection code paths must opt in to include `I_IMAGINED`. Test asserts default and explicit opt-in paths.
- **AC-6.5.** Retrieval by memory_id walks forward to the head of the `supersedes` chain (`superseded_by is None`) by default. An explicit `history=True` flag walks the chain. Test covers both paths.
- **AC-6.6.** An audit-mode retrieval can read any row in a lineage, including superseded ones. Test asserts this path exists and is distinct from default retrieval.

## Implementation

### 6.1 Reserved quota

The context builder runs retrieval in two phases:

1. **Durable phase.** Query durable tiers (REGRET, ACCOMPLISHMENT, WISDOM, AFFIRMATION) for relevance matches. Select up to `DURABLE_MIN_TOKENS` worth of results.
2. **General phase.** Run the normal retrieval against all other tiers with the remaining budget, plus any unused quota from phase 1.

```python
def build_context(query, total_budget) -> list[EpisodicMemory]:
    durable = retrieve(query, tiers=DURABLE_TIERS, max_tokens=DURABLE_MIN_TOKENS)
    used = sum_tokens(durable)
    remaining = total_budget - used
    other = retrieve(query, tiers=NON_DURABLE_TIERS, max_tokens=remaining)
    return durable + other
```

### 6.2 Source-filtered views

Every retrieval call takes an optional `source_filter: set[SourceKind]`. Default for the routing path is `{SourceKind.I_DID}`. Code paths that want other sources must pass them explicitly:

```python
# Routing (default):
retrieve(query)                                       # I_DID only

# Prospection (explicit opt-in):
retrieve(query, source_filter={SourceKind.I_DID, SourceKind.I_IMAGINED})

# Audit (everything):
retrieve(query, source_filter=set(SourceKind))
```

Prospection-returned results carry a visible marker (in any rendered output) so the reader can tell simulated from experienced. See [daydreaming.md](./daydreaming.md) for the context.

### 6.3 Lineage-aware retrieval

Two query modes for retrieval-by-memory-id:

- **Head retrieval (default).** Walks forward through `superseded_by` until `None`. Returns the current view.
- **History retrieval (opt-in).** Walks backward through `supersedes` and returns the full chain in reverse chronological order.

An audit mode bypasses both and returns any specific row.

### Constants

```python
DURABLE_MIN_TOKENS: int = 800
DURABLE_TIERS: frozenset[MemoryTier] = frozenset({
    MemoryTier.REGRET,
    MemoryTier.ACCOMPLISHMENT,
    MemoryTier.AFFIRMATION,
    MemoryTier.WISDOM,
})
NON_DURABLE_TIERS: frozenset[MemoryTier] = frozenset(MemoryTier) - DURABLE_TIERS
```

## Open questions

- **Q6.1.** `DURABLE_MIN_TOKENS` as an absolute is brittle across model sizes. Reformulate as a ratio of `total_budget` (e.g., 10%)? Probably yes; leaving absolute for now so early tests have a simple baseline.
- **Q6.2.** When a durable memory is retrieved, should the retrieval itself be a `last_accessed_at` update? Non-trivial because it writes through an append-only store for a field that INV-6 permits as mutable. Probably yes, but the implementation needs a write path that doesn't violate the append-only invariant for other fields.
