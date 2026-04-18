# Spec 3 — Durability invariants

*Eight invariants that must hold for any memory in REGRET, ACCOMPLISHMENT, or WISDOM, or any memory with `immutable=True`. These are the structural guarantees that make personal memory durable rather than just decay-resistant.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md).
**Depended on by:** write-paths, retrieval, persistence, daydreaming.

---

## Current state

- `clamp_weight()` (main) enforces floors. That is INV-1 below; the other seven don't exist.
- `deleted: bool` on `EpisodicMemory` allows any memory to be soft-deleted, including durable tiers.
- No provenance lock: any `source` value accepts any tier.
- No migration contract preserving durable rows across versions.

## Target

A memory in a durable tier cannot lose its content, cannot be overwritten in place, cannot drift below its floor, and cannot be created from untrusted provenance. Retrieval cannot starve the self of durable memory under budget pressure.

## Acceptance criteria

- **AC-3.1 (INV-1).** Weight of a durable memory cannot be driven below the tier floor by any sequence of `decay()` calls. Property test over random decay sequences.
- **AC-3.2 (INV-2).** Attempting to delete (soft or hard) a memory with `immutable=True` raises at the repository. Negative test.
- **AC-3.3 (INV-3).** Writing REGRET, ACCOMPLISHMENT, or WISDOM with `source != I_DID` raises at the type boundary. Negative test over each bad source.
- **AC-3.4 (INV-4).** Writing a durable memory with `self_id == ""` raises. Negative test.
- **AC-3.5 (INV-5).** A contradicting outcome on a durable memory produces a new superseding row; the original row is unchanged except for `superseded_by` and `contradiction_count`. Property test over random contradiction sequences.
- **AC-3.6 (INV-6).** A durable memory, once written, is never mutated in place except for `superseded_by`, `last_accessed_at`, `reinforcement_count`, and `contradiction_count`. Other fields are frozen. Test asserts this via `__setattr__` guard.
- **AC-3.7 (INV-7).** A simulated version migration that drops any durable row fails CI. Migration-verifier test (see [persistence.md](./persistence.md)).
- **AC-3.8 (INV-8).** Context builder cannot exclude all durable memories under any budget pressure as long as at least one durable memory matches retrieval. Property test.

## Invariants

**INV-1. Floor preservation.** `weight ≥ WEIGHT_BOUNDS[tier][0]` at all times. Enforced by `clamp_weight()`; extended to reject writes that would violate it.

**INV-2. Non-deletion.** `deleted=True` is rejected at the repository when `immutable=True`. Retraction requires minting a successor memory and setting the old row's `superseded_by`.

**INV-3. Provenance lock.** A memory can enter REGRET, ACCOMPLISHMENT, or WISDOM only if `source == SourceKind.I_DID`. The constraint applies both at construction and at any tier promotion.

**INV-4. Self-binding.** `self_id != ""` is required on every durable memory.

**INV-5. Contradiction cannot erase.** A contradicting outcome mints a new row with `supersedes` pointing to the original. The original persists. `contradiction_count` on the original increments. Weight does not go below the tier floor.

**INV-6. Append-only history.** Durable memory rows are mutable only in: `superseded_by` (settable once), `last_accessed_at`, `reinforcement_count`, `contradiction_count`. All other fields are frozen. Updates to content or tier require a new row with `supersedes`.

**INV-7. Migration fidelity.** Every `(self_id, memory_id)` pair in the durable tiers is preserved across version migrations. Migration scripts that would drop durable rows fail CI.

**INV-8. Retrieval quota.** The context builder reserves `DURABLE_MIN_TOKENS` (default 800) for durable-tier retrievals. Under budget pressure, non-durable tiers are cut first. If durable relevance-matches cannot fill the quota, the remainder is released to other tiers.

## Implementation notes

- INV-1 to INV-6 are enforced at the type/repository boundary. A violation should raise before any DB write.
- INV-7 is a CI-level check, not runtime. See [persistence.md](./persistence.md) for the migration verifier.
- INV-8 lives in the context builder. See [retrieval.md](./retrieval.md).

## Open questions

- **Q3.1.** INV-8 defaults `DURABLE_MIN_TOKENS` to 800. Is that calibrated for typical context windows (128k+) or too generous for small models? Probably needs to be a ratio of total context, not an absolute.
- **Q3.2.** INV-6 freezes most fields. Should `intent_at_time` also be mutable to allow post-hoc clarification? Leaning no — mutability there defeats the point of preserving stance at encoding — but worth naming.
