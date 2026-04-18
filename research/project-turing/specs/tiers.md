# Spec 2 — Tier changes: add ACCOMPLISHMENT

*Adds the `ACCOMPLISHMENT` tier and updates weight bounds and inheritance priority. Restores symmetry between durable negative-past (REGRET) and durable positive-past memory.*

**Depends on:** [schema.md](./schema.md).
**Depended on by:** durability-invariants, write-paths, retrieval, persistence, daydreaming.

---

## Current state

From `src/stronghold/types/memory.py`:

- Seven tiers: OBSERVATION, HYPOTHESIS, OPINION, LESSON, REGRET, AFFIRMATION, WISDOM.
- REGRET and AFFIRMATION share `(0.6, 1.0)` weight bounds.
- No tier for past-positive self-implication. AFFIRMATION's name suggests commitment; its current use is overloaded across "I commit" and "I succeeded."

## Target

Introduce **ACCOMPLISHMENT** as the past-positive symmetric counterpart to REGRET. Re-home AFFIRMATION to mean only *forward commitment*. The eight-tier set is the stable vocabulary the rest of the specs rest on.

## Acceptance criteria

- **AC-2.1.** `MemoryTier` enum contains `ACCOMPLISHMENT = "accomplishment"`. Test asserts membership.
- **AC-2.2.** `WEIGHT_BOUNDS[ACCOMPLISHMENT] == (0.6, 1.0)` — identical to `REGRET`. Test asserts exact tuple.
- **AC-2.3.** `clamp_weight(ACCOMPLISHMENT, x)` respects the bounds for `x` across the full float range. Property test.
- **AC-2.4.** `INHERITANCE_PRIORITY[ACCOMPLISHMENT] == 5` — same as REGRET and AFFIRMATION. Test.
- **AC-2.5.** No existing tier's bounds change. Regression test asserts `WEIGHT_BOUNDS` is a superset of the prior set.

## Implementation

```python
class MemoryTier(StrEnum):
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    LESSON = "lesson"
    REGRET = "regret"
    ACCOMPLISHMENT = "accomplishment"   # new
    AFFIRMATION = "affirmation"
    WISDOM = "wisdom"


WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION:    (0.1, 0.5),
    MemoryTier.HYPOTHESIS:     (0.2, 0.6),
    MemoryTier.OPINION:        (0.3, 0.8),
    MemoryTier.LESSON:         (0.5, 0.9),
    MemoryTier.REGRET:         (0.6, 1.0),
    MemoryTier.ACCOMPLISHMENT: (0.6, 1.0),   # new
    MemoryTier.AFFIRMATION:    (0.6, 1.0),
    MemoryTier.WISDOM:         (0.9, 1.0),
}


INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION:    1,
    MemoryTier.HYPOTHESIS:     2,
    MemoryTier.OPINION:        3,
    MemoryTier.LESSON:         4,
    MemoryTier.REGRET:         5,
    MemoryTier.ACCOMPLISHMENT: 5,   # new
    MemoryTier.AFFIRMATION:    5,
    MemoryTier.WISDOM:         6,
}
```

### Tier semantics after this change

| Tier | Direction | Valence | Role |
|---|---|---|---|
| OBSERVATION | Past | Neutral | Noetic fact |
| HYPOTHESIS | Past/present | Neutral | Tentative belief |
| OPINION | Present | Stance | Held view |
| LESSON | Past → future | Corrective | Updated rule |
| REGRET | Past | Negative | Durable self-as-past-actor (failure) |
| ACCOMPLISHMENT | Past | Positive | Durable self-as-past-actor (success) |
| AFFIRMATION | Future | Commitment | Forward self-binding |
| WISDOM | Cross-context | Identity | Distilled selfhood |

### Why the symmetry matters

If regret is unforgettable but success is forgettable, the Conduit's self-model drifts toward self-distrust. Equal weight bounds and equal inheritance priority for REGRET and ACCOMPLISHMENT is the structural correction.

## Open questions

- **Q2.1.** Is AFFIRMATION the right name once ACCOMPLISHMENT exists, or does it read as too close? Alternative: COMMITMENT. Cosmetic but affects readability of write-path specs.
- **Q2.2.** Should LESSON's floor be higher (e.g., 0.6) to reflect that lessons are also self-implicating? Deferred — out of scope here, belongs in a future lesson-durability spec.
