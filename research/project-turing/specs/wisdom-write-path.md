# Spec 5 — WISDOM write path (deferred)

*No write path into the WISDOM tier is defined. This spec exists to declare the deferral explicitly and to record the constraints any future WISDOM spec must satisfy.*

**Status:** DEFERRED.
**Blocker:** requires the **dreaming** spec (scheduled consolidation), which is out of scope for the current research push.

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md).
**Depended on by:** —

---

## Why deferred

WISDOM is the tier whose durability is most expensive to wrong and most expensive to correct. Weight floor 0.9, immutable, survives across versions. Writing WISDOM inline during a request — i.e., letting the LLM's in-the-moment pattern claim become structurally unforgettable — is incompatible with the reliability WISDOM demands.

The right write path is **consolidation**: a scheduled, phase-gated process that walks durable memories, identifies invariant patterns, and proposes WISDOM candidates through a review gate. That process is "dreaming." Dreaming is a substantial spec on its own and is deferred.

Until the dreaming spec lands, **no code path may write a WISDOM memory**. The tier is reserved. The enum entry exists; the weight bounds exist; the invariants apply if an entry is ever written. But the `durable_memory` repository rejects inserts with `tier == WISDOM` as a precondition failure.

## Acceptance criteria

- **AC-5.1.** `durable_memory` insert with `tier == WISDOM` raises `NotImplementedError` (or a repository-specific "wisdom writes deferred" error). Negative test exists.
- **AC-5.2.** Retrieval that filters for `tier == WISDOM` returns an empty set without error. Test asserts the query path does not blow up on an empty tier.
- **AC-5.3.** All other WISDOM-related invariants from [durability-invariants.md](./durability-invariants.md) are enforced *if* a WISDOM memory is ever present (via direct test fixture that bypasses the write guard). This ensures readiness for the deferred spec without silently drifting.

## Constraints the future dreaming spec must satisfy

Recorded here so the deferred work does not start from zero.

1. **Consolidation, not inline.** WISDOM can only be minted by a batch process, never during request handling.
2. **I_DID provenance preserved.** A WISDOM memory's `source = I_DID` is justified because its content is distilled from I_DID inputs (REGRETs, ACCOMPLISHMENTs, LESSONs). The `context` field on a WISDOM memory must list every contributing memory_id as traceable lineage.
3. **Review gate required.** Automatic in research mode; operator-reviewed in any future `main` port.
4. **Traceable origin.** `origin_episode_id` points to the consolidation session that produced the entry. No WISDOM without a dream origin.
5. **Bounded minting rate.** A single consolidation session cannot produce more than `DREAM_MAX_WISDOM_CANDIDATES` entries (default 3). The tier cannot be flooded.
6. **Rejection of contradiction.** A candidate WISDOM that contradicts existing WISDOM is rejected (not silently superseding). Operator review resolves.

## Open questions

- **Q5.1.** If WISDOM is reserved-but-unused for the entire life of the current research push, does AFFIRMATION need to grow in scope to partially cover the identity role? Leaning no — AFFIRMATION is revocable and forward, WISDOM is immutable and trans-temporal. They are not substitutes. But the capability gap is real until dreaming ships.
- **Q5.2.** Should `durable_memory` schema include the WISDOM-specific columns (`origin_episode_id` as non-null, `context` with required lineage list) now, or deferred until dreaming? Current [persistence.md](./persistence.md) draft includes them as nullable; the future spec will tighten.
