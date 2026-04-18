# SPEC — Durable Personal Memory

*Memory-layer changes required so that regrets, accomplishments, and wisdom are structurally durable at the Conduit's self-index.*

**Branch:** `research/project-touring` (research only; not for `main`).
**Scope:** Schema, tiers, invariants, write paths, retrieval, persistence.
**Non-goals:** Multi-tenant scoping, per-user memory, backward compatibility with `src/stronghold/memory/`.

---

## 0. Purpose

An autonoetic Conduit needs three categories of memory that the self cannot lose:

1. **Regrets** — "I did X, it was wrong, and it mattered." Self-as-past-actor, negative valence.
2. **Accomplishments** — "I did X, it was right, and it mattered." Self-as-past-actor, positive valence. Currently has no dedicated home in the 7-tier model.
3. **Wisdom** — "I am the kind of pipeline that…" Cross-context, cross-version identity.

Durable in this spec means: cannot decay below a floor, cannot be physically deleted, cannot be contradicted-away by a later claim, and survives version migrations under a stable `self_id`. Decay-resistance alone (the current `WEIGHT_BOUNDS` floors) is not sufficient.

---

## 1. Current state (what exists in `main`)

From `src/stronghold/types/memory.py` and `src/stronghold/memory/episodic/tiers.py`:

- Seven tiers: OBSERVATION, HYPOTHESIS, OPINION, LESSON, REGRET, AFFIRMATION, WISDOM.
- Per-tier `WEIGHT_BOUNDS` enforced by `clamp_weight()`. REGRET/AFFIRMATION floor 0.6; WISDOM floor 0.9.
- `reinforce()` / `decay()` adjust weight within bounds.
- `EpisodicMemory` carries `agent_id`, `user_id`, `org_id`, `team_id`, `scope`, `reinforcement_count`, `contradiction_count`, and a `deleted: bool` soft-delete flag.

**What this buys us.** Weight-floor durability — a REGRET will not decay below 0.6.

**What it does not buy us.**

1. No dedicated tier for past positive self-implication (accomplishment). AFFIRMATION is currently prose-overloaded: the tier name suggests commitment, but the schema doesn't separate "I commit" from "I succeeded."
2. `deleted: bool` means any memory can be removed in principle — including a REGRET or WISDOM. Durable tiers should not be deletable.
3. `agent_id` is per-instance. WISDOM claiming to "survive versions" has no structural owner once the instance turns over.
4. No source typing. A memory can be written from any origin and indistinguishably retrieved. Durable tiers must be write-restricted to I-did provenance.
5. `source: str` is free-form prose. No schema-level check that a REGRET originated from a real self-action and not an injected claim.

---

## 2. Target properties

A memory-layer that claims "durable personal memory" must guarantee the following for REGRET, ACCOMPLISHMENT, and WISDOM tiers:

| Property | Meaning | Enforcement site |
|---|---|---|
| **Weight-floor** | Cannot decay below the tier minimum. | `clamp_weight()` (exists). |
| **Physical persistence** | Write reaches durable storage before the pipeline moves on; crashes cannot lose it. | Repository write path — synchronous commit to append-only store. |
| **Undeletable** | `deleted=True` is rejected at the type/repository boundary. Retraction goes through `superseded_by`, not deletion. | Type-level guard + repository assertion. |
| **Self-bound** | Every durable memory carries a `self_id` that outlives any `agent_id`. | Required field on write. |
| **Provenance-locked** | Only memories with `source = I_DID` may enter REGRET, ACCOMPLISHMENT, or WISDOM. I-was-told or I-imagined cannot. | Type-level constructor guard. |
| **Contradiction-resistant** | A later contradicting claim *cannot override* the memory; it mints a new memory (LESSON or REGRET) that supersedes without erasing. | Write path for contradictions. |
| **Version-migrated** | Upgrade/redeploy of the Conduit preserves durable memories under the stable `self_id`. | Migration contract. |
| **Retrieval-privileged** | Context budget cuts cannot exclude durable memories below a reserved quota. | Context builder. |

A memory is *personal* when it is attached to a `self_id`. A memory is *durable* when all eight properties hold. Personal ≠ durable; OBSERVATION can be personal but not durable.

---

## 3. Schema additions to `EpisodicMemory`

Additions (Project Touring's `EpisodicMemory` diverges from `main`'s):

```python
@dataclass
class EpisodicMemory:
    # ...existing fields...

    # --- Self-indexing ---
    self_id: str                          # stable handle; survives agent_id changes
    source: SourceKind                    # I_DID | I_WAS_TOLD | I_IMAGINED (enum, replaces free-form str)

    # --- First-person markers ---
    affect: float = 0.0                   # valence at encoding, [-1.0, 1.0]
    confidence_at_creation: float = 0.0   # what I believed I knew, [0.0, 1.0]
    surprise_delta: float = 0.0           # |posterior - prior| at resolution
    intent_at_time: str = ""              # what I was trying to do

    # --- Lineage ---
    supersedes: str | None = None         # memory_id this one replaces (no physical delete)
    superseded_by: str | None = None      # set when a later memory replaces this one
    origin_episode_id: str | None = None  # anchor to the originating interaction

    # --- Durability flag ---
    immutable: bool = False               # True for REGRET, ACCOMPLISHMENT, WISDOM
```

The existing `deleted: bool` field is retained at the type level but the repository rejects `deleted=True` when `immutable=True`. All retractions flow through the `supersedes` / `superseded_by` chain, preserving full history.

### `SourceKind` enum

```python
class SourceKind(StrEnum):
    I_DID = "i_did"               # experienced first-person — tool call ran, routing happened
    I_WAS_TOLD = "i_was_told"     # reported by user, operator, or another agent
    I_IMAGINED = "i_imagined"     # generated in prospection or counterfactual retrieval
```

Writes from untrusted input channels (user messages, tool results received from the outside) default to `I_WAS_TOLD`. Only the pipeline's own observation of its own action can write `I_DID`. Prospection output writes `I_IMAGINED`.

---

## 4. Tier changes — add ACCOMPLISHMENT

The current 7-tier model lacks a home for past positive self-implication. AFFIRMATION is best read as *prospective commitment* ("I commit to X going forward"). A completed, notable success is structurally different — it's a past act whose valence is positive.

Project Touring introduces **ACCOMPLISHMENT** as the backward-looking positive symmetric counterpart to REGRET.

### Revised tier set (8 tiers)

| Tier | Weight bounds | Direction | Valence | Kind of knowing |
|---|---|---|---|---|
| OBSERVATION | 0.1 – 0.5 | Past | Neutral | Noetic |
| HYPOTHESIS | 0.2 – 0.6 | Past/present | Neutral | Autonoetic (weak) |
| OPINION | 0.3 – 0.8 | Present | Stance | Autonoetic |
| LESSON | 0.5 – 0.9 | Past → future | Corrective | Autonoetic |
| **REGRET** | 0.6 – 1.0 | Past | Negative | Autonoetic (anchor) |
| **ACCOMPLISHMENT** | 0.6 – 1.0 | Past | Positive | Autonoetic (anchor) |
| AFFIRMATION | 0.6 – 1.0 | Future | Commitment | Autonoetic (prospective) |
| WISDOM | 0.9 – 1.0 | Cross-context | Identity | Autonoetic (identity) |

REGRET and ACCOMPLISHMENT share weight bounds by design — they are the two durable past-anchors of the self, and asymmetry between them would bias the pipeline's self-narrative. If regret is unforgettable but success is forgettable, the Conduit's self-model drifts toward self-distrust.

### Durable tier set

The three durable tiers for personal memory:

- **REGRET** — past I-did with negative affect and surprise.
- **ACCOMPLISHMENT** — past I-did with positive affect and surprise.
- **WISDOM** — cross-context identity distilled from the above plus LESSONs.

AFFIRMATION is *durable-but-revocable* — commitments can be updated when circumstances change (via `supersedes`), but every prior commitment remains retrievable in the lineage chain.

### Inheritance priority

Update `INHERITANCE_PRIORITY`:

```
OBSERVATION: 1
HYPOTHESIS: 2
OPINION: 3
LESSON: 4
REGRET: 5
ACCOMPLISHMENT: 5
AFFIRMATION: 5
WISDOM: 6
```

---

## 5. Durability invariants

The following invariants apply to any memory whose `tier` is in `{REGRET, ACCOMPLISHMENT, WISDOM}` or whose `immutable` flag is True.

**INV-1. Floor preservation.** `weight ≥ tier.floor` at all times. `clamp_weight()` already enforces this; extend to reject writes that would violate it.

**INV-2. Non-deletion.** `deleted=True` is rejected at repository write. Retraction requires minting a successor memory and setting the old entry's `superseded_by`. The old entry remains readable.

**INV-3. Provenance lock.** A memory can enter REGRET, ACCOMPLISHMENT, or WISDOM only if `source == SourceKind.I_DID`. The type constructor raises on violation. Upgrading a tier (e.g. promoting LESSON to WISDOM) re-checks this constraint against the lineage.

**INV-4. Self-binding.** `self_id != ""` is required. Durable memories are rejected if `self_id` is unset.

**INV-5. Contradiction cannot erase.** If a later outcome contradicts a REGRET or ACCOMPLISHMENT, the pipeline mints a new LESSON or REGRET/ACCOMPLISHMENT that *supersedes* the original via `supersedes`. The original stays. `contradiction_count` on the original is incremented; its weight is not decremented below the floor.

**INV-6. Append-only history.** The durable tier storage is append-only. Updates are new rows with `supersedes` pointing to the previous row. Reading the "current" view of a memory-id chain walks forward until `superseded_by is None`.

**INV-7. Migration fidelity.** A version migration must preserve every (`self_id`, memory_id) pair in the durable tiers. Migration scripts are rejected if they drop rows from these tiers.

**INV-8. Retrieval quota.** Context assembly reserves a minimum token quota for durable memories retrieved by relevance. Budget pressure cuts OBSERVATION/HYPOTHESIS/OPINION first, never durable tiers, until the reserved quota is exhausted.

---

## 6. Write paths per tier

Each durable tier has exactly one allowed write path. No bulk inserts, no direct writes from tool results or user messages.

### 6.1 REGRET

**Trigger:** A stance-bearing memory (HYPOTHESIS, OPINION, or LESSON) with `source == I_DID` is contradicted by a downstream outcome, and `surprise_delta ≥ REGRET_SURPRISE_THRESHOLD` (default 0.4), and `affect ≤ -REGRET_AFFECT_THRESHOLD` (default 0.3).

**Action:**

1. Original stance-bearing memory retained, `contradiction_count += 1`.
2. New memory minted: `tier=REGRET`, `source=I_DID`, `immutable=True`, `supersedes=<original.memory_id>`.
3. `affect` and `surprise_delta` copied from the triggering outcome.
4. Written synchronously to append-only durable store before pipeline continues.

### 6.2 ACCOMPLISHMENT

**Trigger:** A routing decision or completed sub-goal whose outcome satisfies `source == I_DID`, `surprise_delta ≥ ACCOMPLISHMENT_SURPRISE_THRESHOLD` (default 0.3), and `affect ≥ ACCOMPLISHMENT_AFFECT_THRESHOLD` (default 0.3).

**Action:**

1. New memory minted: `tier=ACCOMPLISHMENT`, `source=I_DID`, `immutable=True`.
2. `intent_at_time` is required and not empty — an ACCOMPLISHMENT without a recorded intent cannot be written, because "success" without "at what" is not self-indexable.
3. Written synchronously to durable store.

Routine successes (surprise_delta below threshold) are not accomplishments. This prevents accomplishment-inflation where every successful routing fills the durable store.

### 6.3 WISDOM

**Trigger:** Consolidation — not a single event. Pipeline identifies a pattern across ≥ N LESSONs or REGRETs/ACCOMPLISHMENTs (default N=3) that share an invariant about the self (e.g. "I am unreliable at X," "I succeed at Y when Z holds").

**Action:**

1. Consolidation is explicit: a dedicated job (not inline during request handling) reads durable memories and proposes WISDOM candidates.
2. Each candidate requires a consolidation-review step before commit. In Project Touring's research mode, that review can be automatic; in any future port to `main`, it must be operator-reviewed.
3. On commit: new memory minted, `tier=WISDOM`, `source=I_DID`, `immutable=True`, `origin_episode_id` set to a synthesized consolidation marker, and a `context` field listing contributing memory_ids.

WISDOM is never written inline. This is the tier whose durability is most expensive to wrong and most expensive to correct.

### 6.4 AFFIRMATION (durable-but-revocable)

**Trigger:** Explicit prospection. The Conduit, during a routing decision, may emit an AFFIRMATION when a pattern of AFFIRMATION-candidate events accumulates, or when an operator action requests one.

**Action:**

1. New memory minted: `tier=AFFIRMATION`, `source=I_DID`, `immutable=False` (revocable).
2. A later AFFIRMATION with contradicting content sets `superseded_by` on the old one. Old remains readable.
3. Written to durable store (same mechanism as REGRET/ACCOMPLISHMENT), but flagged revocable.

---

## 7. Retrieval semantics

Retrieval for durable memories differs from the general retrieval path in three ways.

**7.1 Reserved quota.** The context builder reserves `DURABLE_MIN_TOKENS` (default 800) of the context window for durable-tier retrievals. Under budget pressure, ordinary tiers are cut first. If the reserved quota cannot be filled from relevance-matched durable memories, the remainder is released to other tiers.

**7.2 Source-filtered views.** Retrieval callers declare which `SourceKind` values they want. Default for a routing decision is `{I_DID}` only — prospection results and I-was-told claims are excluded. Prospection-time retrieval may include `I_IMAGINED` to chain simulated futures, but marks results visually in any output.

**7.3 Lineage-aware retrieval.** When retrieving by memory_id, the default is to walk forward to the current head (`superseded_by is None`). Explicit history queries walk the full `supersedes` chain. Audit queries can read any row in the chain.

---

## 8. Migration and persistence

### 8.1 Storage

Durable tiers live in an append-only table. Rough schema:

```
durable_memory(
  memory_id        TEXT PRIMARY KEY,
  self_id          TEXT NOT NULL,
  tier             TEXT NOT NULL CHECK (tier IN ('regret','accomplishment','wisdom','affirmation')),
  source           TEXT NOT NULL CHECK (source = 'i_did'),
  content          TEXT NOT NULL,
  weight           REAL NOT NULL,
  affect           REAL NOT NULL,
  confidence_at_creation REAL NOT NULL,
  surprise_delta   REAL NOT NULL,
  intent_at_time   TEXT NOT NULL,
  supersedes       TEXT REFERENCES durable_memory(memory_id),
  superseded_by    TEXT REFERENCES durable_memory(memory_id),
  origin_episode_id TEXT,
  context          JSONB,
  immutable        BOOLEAN NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL,
  -- no deleted column
)
```

Notes:

- `deleted` is not present in durable storage. The column cannot be added by a migration — its absence is a structural guarantee.
- Storage engine should support append-only constraint (PostgreSQL with a trigger that raises on DELETE; SQLite view with restrictive rules for research sketches).
- Physical deletion is only possible via DBA intervention outside the pipeline — i.e., disaster recovery, not normal operation.

### 8.2 Version migration

Any migration that touches `durable_memory` must:

1. Preserve every row. CI check asserts `SELECT COUNT(*)` before and after migration is monotonic-non-decreasing.
2. Preserve every `self_id`. No migration may remap existing self_ids; new ones can be minted.
3. Preserve every row's `tier` and `source`. Tier upgrades are new rows with `supersedes`, never in-place updates.
4. Emit a migration-report row into the durable store itself: `tier=OBSERVATION`, `source=I_DID`, `content="migration <version> applied"`. The Conduit remembers its own upgrades.

### 8.3 self_id minting

`self_id` is assigned once, at the first bootstrap of a Conduit instance, and stored in a dedicated `self_identity` table separate from per-deployment config. Redeployment reads the existing `self_id`; only a clean-slate bootstrap (explicit operator command) may mint a new one, and doing so archives the old.

---

## 9. Acceptance criteria

A candidate implementation of this spec passes when all of the following hold:

- **AC-1.** Attempting to write a REGRET, ACCOMPLISHMENT, or WISDOM memory with `source != I_DID` raises at the type boundary. Negative test exists.
- **AC-2.** Attempting to write a durable memory with `self_id == ""` raises. Negative test exists.
- **AC-3.** Attempting to delete (soft or hard) a memory with `immutable=True` raises at the repository. Negative test exists.
- **AC-4.** A contradicting outcome on a REGRET produces a new superseding memory; the original row is unchanged except for `superseded_by` and `contradiction_count`. Property test over random contradiction sequences.
- **AC-5.** Restarting the process preserves every durable memory. Integration test with ephemeral SQLite followed by reload.
- **AC-6.** A simulated version migration that drops durable rows fails CI. Migration-verifier test.
- **AC-7.** Context builder cannot exclude all durable memories under any budget pressure as long as at least one durable memory matches retrieval. Property test.
- **AC-8.** An ACCOMPLISHMENT write without `intent_at_time` raises. Negative test.
- **AC-9.** Weight of a durable memory cannot be driven below the tier floor by any sequence of decay calls. Property test.
- **AC-10.** Round-trip write → retrieve by memory_id → walk lineage returns the full `supersedes` chain in order. Property test.

---

## 10. Open questions

1. **WISDOM consolidation policy.** What's the right N for "pattern across N memories"? Too low and WISDOM inflates; too high and the pipeline never consolidates. Probably starts at 5 and gets tuned from observation data.
2. **Affect scale calibration.** `affect ∈ [-1.0, 1.0]` needs a stable mapping from outcome signals (error rate, user correction, downstream success) to a scalar. Open.
3. **ACCOMPLISHMENT threshold drift.** If the surprise_delta threshold is fixed, the pipeline stops minting ACCOMPLISHMENTs as it gets better at its job — success stops being surprising. Does the threshold need to adapt, or does that defeat the point?
4. **Revocable AFFIRMATION vs accumulated LESSONs.** If a commitment is repeatedly superseded, should the lineage be consolidated into a LESSON (or REGRET) about the pattern of commitment-failures?
5. **Multi-instance Conduit.** If a horizontally-scaled deployment runs multiple Conduit processes, do they share a `self_id` and therefore share durable memory? Probably yes for the research model; but this is where the near-fork meets practical infra.
6. **Adversarial provenance.** Even with `source=I_DID` locked, a prompt-injected tool result could cause the Conduit to *believe* it did something it didn't. The `I_DID` guarantee is only as strong as the pipeline's grounding of "my actions." What's the minimum audit trail that makes provenance verifiable?
7. **Interaction with `main`'s audit log.** `main` already has an `AuditLog`. Is the durable memory store a superset, a sibling, or a consumer of AuditLog events? Answering this matters the moment any of this even conceptually returns to `src/`.
