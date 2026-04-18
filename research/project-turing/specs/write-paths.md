# Spec 4 — Write paths for REGRET, ACCOMPLISHMENT, AFFIRMATION

*Triggers and actions for the three non-WISDOM durable tiers. Each tier has exactly one allowed write path; nothing else in the codebase may construct a memory in these tiers.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md).
**Depended on by:** [daydreaming.md](./daydreaming.md) (negatively — daydream code path cannot reach these).

---

## Current state

- `main` has no explicit write paths for REGRET or AFFIRMATION. The tiers exist in the enum; what fires a write is undefined.
- ACCOMPLISHMENT does not yet exist (see [tiers.md](./tiers.md)).

## Target

Each durable tier has a named trigger, a threshold set, and an action. The thresholds are tunable constants; the path shapes are fixed.

## Acceptance criteria

- **AC-4.1.** A REGRET write requires a preceding stance-bearing memory (HYPOTHESIS, OPINION, or LESSON) with `source == I_DID` that is contradicted by outcome. A REGRET write without such a preceding memory raises. Negative test.
- **AC-4.2.** An ACCOMPLISHMENT write without non-empty `intent_at_time` raises. Negative test.
- **AC-4.3.** Thresholds (`REGRET_SURPRISE_THRESHOLD`, `REGRET_AFFECT_THRESHOLD`, `ACCOMPLISHMENT_SURPRISE_THRESHOLD`, `ACCOMPLISHMENT_AFFECT_THRESHOLD`) are exposed as configuration constants and honored. Parametrized test over values above and below threshold asserts only above-threshold triggers mint memories.
- **AC-4.4.** An AFFIRMATION write produces `immutable=False`; later contradicting AFFIRMATION sets `superseded_by` on the old one. Property test over sequences of conflicting commitments.
- **AC-4.5.** Every write in these paths is synchronous; the pipeline does not advance past the triggering event until the write has committed to the durable store. Integration test with a hook that delays the DB write and asserts ordering.
- **AC-4.6.** Durable writes go to the append-only `durable_memory` table (see [persistence.md](./persistence.md)), never to the general episodic store. Test asserts routing.

## Implementation

### 4.1 REGRET

**Trigger:** A stance-bearing memory `M` (tier in `{HYPOTHESIS, OPINION, LESSON}`) with `M.source == I_DID` is contradicted by a downstream outcome, and:

- `surprise_delta ≥ REGRET_SURPRISE_THRESHOLD` (default 0.4)
- `affect ≤ -REGRET_AFFECT_THRESHOLD` (default 0.3)

**Action:**

1. `M.contradiction_count += 1`. Nothing else on `M` changes.
2. Mint a new memory `R`:
   - `tier = REGRET`
   - `source = I_DID`
   - `immutable = True`
   - `supersedes = M.memory_id`
   - `affect` and `surprise_delta` from the triggering outcome
   - `intent_at_time` inherited from `M`
3. Write `R` synchronously to `durable_memory`.
4. Set `M.superseded_by = R.memory_id` (the only permitted in-place change per INV-6).

### 4.2 ACCOMPLISHMENT

**Trigger:** A routing decision or completed sub-goal whose resolution satisfies:

- `source == I_DID`
- `surprise_delta ≥ ACCOMPLISHMENT_SURPRISE_THRESHOLD` (default 0.3)
- `affect ≥ ACCOMPLISHMENT_AFFECT_THRESHOLD` (default 0.3)
- `intent_at_time` is non-empty

**Action:**

1. Mint a new memory `A`:
   - `tier = ACCOMPLISHMENT`
   - `source = I_DID`
   - `immutable = True`
   - `intent_at_time` populated (required)
2. Write `A` synchronously to `durable_memory`.

Routine successes (surprise below threshold) are not accomplishments. This prevents durable-store inflation.

### 4.3 AFFIRMATION

**Trigger:** An explicit commitment event. Two paths:

- **Pattern-driven.** After N affirmation-candidate events within a window (e.g., three successful routings that followed the same principle), the Conduit emits an AFFIRMATION expressing the principle.
- **Operator-driven.** An operator command issues an AFFIRMATION directly.

**Action:**

1. Mint a new memory `F`:
   - `tier = AFFIRMATION`
   - `source = I_DID`
   - `immutable = False` (revocable)
2. If a prior AFFIRMATION exists that contradicts `F`, set `F.supersedes = prior.memory_id` and then set `prior.superseded_by = F.memory_id`.
3. Write `F` synchronously to `durable_memory`.

Revocable means future contradiction can supersede it. Durable means the predecessor is never deleted; the full lineage is walkable.

### Configuration constants

```python
REGRET_SURPRISE_THRESHOLD:         float = 0.4
REGRET_AFFECT_THRESHOLD:           float = 0.3
ACCOMPLISHMENT_SURPRISE_THRESHOLD: float = 0.3
ACCOMPLISHMENT_AFFECT_THRESHOLD:   float = 0.3
```

All overridable via config. Calibration is a tuning problem per deployment.

## Open questions

- **Q4.1.** ACCOMPLISHMENT threshold drift: as the pipeline gets better at its job, successes stop being surprising and the tier stops growing. Adaptive threshold? Fixed threshold + accept the sparsity? Open.
- **Q4.2.** Should REGRET require a preceding I_DID stance, or can it be minted directly from an unmediated failure outcome? Current spec says yes (tied to a stance); the alternative is a looser coupling where regret can mint from observation-of-self-action alone.
- **Q4.3.** AFFIRMATION pattern-driven trigger uses N=3 candidates. Tuning the window and N is open.
