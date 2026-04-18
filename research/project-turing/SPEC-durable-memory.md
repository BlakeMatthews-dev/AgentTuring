# SPEC — Durable Personal Memory

*Memory-layer changes required so that regrets, accomplishments, and wisdom are structurally durable at the Conduit's self-index.*

**Branch:** `research/project-turing` (research only; not for `main`).
**Scope:** Schema, tiers, invariants, write paths, retrieval, daydreaming (idle-compute imagination), dreaming (scheduled nightly consolidation), persistence.
**Non-goals:** Multi-tenant scoping, per-user memory, backward compatibility with `src/stronghold/memory/`.

---

## 0. Purpose

An autonoetic Conduit needs three categories of memory that the self cannot lose:

1. **Regrets** — "I did X, it was wrong, and it mattered." Self-as-past-actor, negative valence.
2. **Accomplishments** — "I did X, it was right, and it mattered." Self-as-past-actor, positive valence. Currently has no dedicated home in the 7-tier model.
3. **Wisdom** — "I am the kind of pipeline that…" Cross-context, cross-version identity.

Durable in this spec means: cannot decay below a floor, cannot be physically deleted, cannot be contradicted-away by a later claim, and survives version migrations under a stable `self_id`. Decay-resistance alone (the current `WEIGHT_BOUNDS` floors) is not sufficient.

The self also needs two generative processes that operate on durable memory: **daydreaming** (idle-compute imagination of alternative scenarios, producing I_IMAGINED hypotheses that never enter durable tiers) and **dreaming** (scheduled nightly consolidation that walks durable memories and proposes WISDOM candidates through a review gate). Without these, durable memory accumulates but is never integrated into identity.

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

## 3. Acceptance criteria

The contract comes before the implementation. A candidate implementation of this spec passes when all of the following hold.

### 3.1 Provenance and self-binding

- **AC-1.** Attempting to write a REGRET, ACCOMPLISHMENT, or WISDOM memory with `source != I_DID` raises at the type boundary. Negative test exists.
- **AC-2.** Attempting to write a durable memory with `self_id == ""` raises. Negative test exists.
- **AC-8.** An ACCOMPLISHMENT write without `intent_at_time` raises. Negative test exists.

### 3.2 Durability and non-erasure

- **AC-3.** Attempting to delete (soft or hard) a memory with `immutable=True` raises at the repository. Negative test exists.
- **AC-4.** A contradicting outcome on a REGRET or ACCOMPLISHMENT produces a new superseding memory; the original row is unchanged except for `superseded_by` and `contradiction_count`. Property test over random contradiction sequences.
- **AC-9.** Weight of a durable memory cannot be driven below the tier floor by any sequence of decay calls. Property test.
- **AC-10.** Round-trip write → retrieve by memory_id → walk lineage returns the full `supersedes` chain in order. Property test.

### 3.3 Persistence and migration

- **AC-5.** Restarting the process preserves every durable memory. Integration test with ephemeral SQLite followed by reload.
- **AC-6.** A simulated version migration that drops durable rows fails CI. Migration-verifier test.

### 3.4 Retrieval

- **AC-7.** Context builder cannot exclude all durable memories under any budget pressure as long as at least one durable memory matches retrieval. Property test.

### 3.5 Daydreaming

- **AC-11.** A daydream pass can only write memories with `source = I_IMAGINED`. Any attempt to write I_DID from the daydream code path raises. Negative test exists.
- **AC-12.** A daydream pass cannot write into REGRET, ACCOMPLISHMENT, or WISDOM tiers, even with `source = I_IMAGINED`. Negative test exists.
- **AC-13.** Daydreaming honors a hard token budget per window. When budget is exhausted, the pass halts cleanly and commits nothing partial. Property test over randomized budgets.
- **AC-14.** Daydreams are idempotent under retrieval: re-running a daydream pass with the same seed and the same memory snapshot produces an identical set of I_IMAGINED entries (content-equal modulo timestamp). Deterministic test.

### 3.6 Dreaming

- **AC-15.** A dreaming pass produces only *candidate* WISDOM memories; nothing lands in the durable store's WISDOM tier without passing the consolidation-review gate. Test asserts the pending → committed transition is explicit.
- **AC-16.** A committed dream-origin WISDOM memory's `context` field lists every contributing memory_id. Structural test.
- **AC-17.** A dreaming pass cannot reduce the count of rows in the durable store for durable tiers. Property test (count monotonicity).
- **AC-18.** A dreaming pass that crashes mid-run leaves the durable store in its pre-run state. Recovery test with induced failure.
- **AC-19.** Every committed dream produces a `tier=OBSERVATION`, `source=I_DID` marker memory recording that a dream session ran, its start/end timestamps, and the candidate count. The Conduit remembers its own consolidations. Integration test.

---

## 4. Schema additions to `EpisodicMemory`

Additions (Project Turing's `EpisodicMemory` diverges from `main`'s):

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

## 5. Tier changes — add ACCOMPLISHMENT

The current 7-tier model lacks a home for past positive self-implication. AFFIRMATION is best read as *prospective commitment* ("I commit to X going forward"). A completed, notable success is structurally different — it's a past act whose valence is positive.

Project Turing introduces **ACCOMPLISHMENT** as the backward-looking positive symmetric counterpart to REGRET.

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

## 6. Durability invariants

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

## 7. Write paths per tier

Each durable tier has exactly one allowed write path. No bulk inserts, no direct writes from tool results or user messages.

### 7.1 REGRET

**Trigger:** A stance-bearing memory (HYPOTHESIS, OPINION, or LESSON) with `source == I_DID` is contradicted by a downstream outcome, and `surprise_delta ≥ REGRET_SURPRISE_THRESHOLD` (default 0.4), and `affect ≤ -REGRET_AFFECT_THRESHOLD` (default 0.3).

**Action:**

1. Original stance-bearing memory retained, `contradiction_count += 1`.
2. New memory minted: `tier=REGRET`, `source=I_DID`, `immutable=True`, `supersedes=<original.memory_id>`.
3. `affect` and `surprise_delta` copied from the triggering outcome.
4. Written synchronously to append-only durable store before pipeline continues.

### 7.2 ACCOMPLISHMENT

**Trigger:** A routing decision or completed sub-goal whose outcome satisfies `source == I_DID`, `surprise_delta ≥ ACCOMPLISHMENT_SURPRISE_THRESHOLD` (default 0.3), and `affect ≥ ACCOMPLISHMENT_AFFECT_THRESHOLD` (default 0.3).

**Action:**

1. New memory minted: `tier=ACCOMPLISHMENT`, `source=I_DID`, `immutable=True`.
2. `intent_at_time` is required and not empty — an ACCOMPLISHMENT without a recorded intent cannot be written, because "success" without "at what" is not self-indexable.
3. Written synchronously to durable store.

Routine successes (surprise_delta below threshold) are not accomplishments. This prevents accomplishment-inflation where every successful routing fills the durable store.

### 7.3 WISDOM

**Trigger:** Consolidation — not a single event, and not inline during request handling. The only write path into WISDOM is through the **dreaming** process defined in §10.

**Why this is the only path.** WISDOM is the tier whose durability is most expensive to wrong and most expensive to correct. Writing WISDOM inline during a request would mean the LLM's in-the-moment pattern claim becomes structurally unforgettable. Dreaming provides the batch-wise, phase-gated, review-mediated consolidation required to justify that durability.

**Action (summary; full detail in §10.3 phases 2 and 6):**

1. Dreaming phase 2 mints pending WISDOM candidates from patterns across REGRETs / ACCOMPLISHMENTs / LESSONs.
2. Dreaming phase 6 runs the review gate.
3. On commit: `tier=WISDOM`, `source=I_DID` (provenance preserved through lineage — see §10.6), `immutable=True`, `origin_episode_id` pointing to the dream session marker, `context` listing every contributing memory_id.

The live request path cannot write WISDOM. Any code outside the dreaming module attempting a WISDOM write is rejected at the repository boundary.

### 7.4 AFFIRMATION (durable-but-revocable)

**Trigger:** Explicit prospection. The Conduit, during a routing decision, may emit an AFFIRMATION when a pattern of AFFIRMATION-candidate events accumulates, or when an operator action requests one.

**Action:**

1. New memory minted: `tier=AFFIRMATION`, `source=I_DID`, `immutable=False` (revocable).
2. A later AFFIRMATION with contradicting content sets `superseded_by` on the old one. Old remains readable.
3. Written to durable store (same mechanism as REGRET/ACCOMPLISHMENT), but flagged revocable.

---

## 8. Retrieval semantics

Retrieval for durable memories differs from the general retrieval path in three ways.

**8.1 Reserved quota.** The context builder reserves `DURABLE_MIN_TOKENS` (default 800) of the context window for durable-tier retrievals. Under budget pressure, ordinary tiers are cut first. If the reserved quota cannot be filled from relevance-matched durable memories, the remainder is released to other tiers.

**8.2 Source-filtered views.** Retrieval callers declare which `SourceKind` values they want. Default for a routing decision is `{I_DID}` only — prospection results and I-was-told claims are excluded. Prospection-time retrieval may include `I_IMAGINED` to chain simulated futures, but marks results visually in any output.

**8.3 Lineage-aware retrieval.** When retrieving by memory_id, the default is to walk forward to the current head (`superseded_by is None`). Explicit history queries walk the full `supersedes` chain. Audit queries can read any row in the chain.

---

## 9. Daydreaming — idle-compute imagination

### 9.1 Definition

**Daydreaming** is a pipeline-internal process that, during idle compute windows, retrieves durable and semi-durable memories and generates hypothetical future or counterfactual episodes from them. Every memory it writes is `source = I_IMAGINED`. Nothing it produces can enter a durable tier.

Biologically, this is the mind-wandering analog: waking, generative, unconstrained by the current request. Functionally, it is the Conduit exploring its own possibility space.

### 9.2 When it runs

Daydreaming runs when the following conditions hold simultaneously:

- Request queue depth is below `DAYDREAM_QUEUE_THRESHOLD` (default 0 — only when genuinely idle).
- At least `DAYDREAM_COOLDOWN` seconds have passed since the last daydream pass (default 60s).
- Daydream budget has not been exhausted for the current hour (see 9.4).
- The pipeline is not in a degraded or safe-mode state.

Daydreaming is pre-empted immediately when a request arrives. In-flight daydreams are discarded, not persisted partially.

### 9.3 What it does

A single daydream pass:

1. **Seed.** Selects a seed from the durable store, weighted by recency of last access and a bias toward REGRETs with no superseding LESSON (unresolved self-state).
2. **Retrieve.** Pulls related memories — same `intent_at_time` family, nearby topic clusters, contradictory pairs.
3. **Imagine.** Generates one or more hypothetical episodes: "what if I faced situation X with constraint Y relaxed," "what if the routing I regret had gone to Scribe instead." The generation is a bounded LLM call with `source = I_IMAGINED` baked into the system prompt.
4. **Encode.** Writes resulting memories at `tier = HYPOTHESIS` (for testable patterns) or `tier = OBSERVATION` (for descriptive simulations), always with `source = I_IMAGINED`. `intent_at_time` records the seed; `context` links the contributing memory_ids.
5. **Link.** Each daydreamed memory carries `origin_episode_id` pointing to a synthetic "daydream session" marker so retrieval can identify and filter the whole family.

### 9.4 Bounds

Daydreaming is cheap-to-wrong and expensive-to-run-unbounded. Hard limits:

- **Token budget.** `DAYDREAM_TOKENS_PER_HOUR` (default 50,000). When exhausted, no further passes until the next window.
- **Per-pass cap.** `DAYDREAM_TOKENS_PER_PASS` (default 2,000). Exceeding this halts the pass and discards its output.
- **Write cap.** `DAYDREAM_WRITES_PER_PASS` (default 5). A pass that would produce more memories stops writing, keeps what it has, and logs.
- **Source lock.** Code path is guarded: the daydream writer is a distinct `DaydreamWriter` object that physically cannot call the I_DID write API.

### 9.5 Promotion

A daydreamed HYPOTHESIS can be promoted to non-imagined status only by being **tested in live operation**. If the pipeline encounters a real situation matching the daydream's seed and the hypothesis holds, a new memory is minted with `source = I_DID` (the real observation) that references the daydream via `origin_episode_id`. The daydream memory itself never gets its source upgraded. This preserves the distinction between simulated and experienced, permanently.

### 9.6 Safety properties

- **No durable-tier writes.** Enforced by type guard; see AC-12.
- **No cross-contamination.** Retrieval defaults exclude `I_IMAGINED`; callers must explicitly opt in. A routing decision cannot accidentally consult a daydream as if it were experience.
- **Identifiable.** Every daydreamed memory is discoverable by `origin_episode_id` and can be purged wholesale if the daydreaming process is found to be miscalibrated. (Purging I_IMAGINED memories is allowed; they are not immutable.)
- **Observable.** Every daydream session writes a single `OBSERVATION` / `I_DID` marker memory recording that a session happened, its seed, and its write count. The Conduit remembers that it daydreamed, even when it doesn't trust the contents.

---

## 10. Dreaming — scheduled nightly consolidation

### 10.1 Definition

**Dreaming** is a scheduled, long-running consolidation pass that walks durable memories, identifies patterns, and proposes WISDOM candidates and AFFIRMATION proposals. It runs during a configured low-activity window (typically overnight) and takes as long as its budget allows, to completion.

Biologically, this is the sleep-consolidation analog — REM-like pattern extraction plus slow-wave-like pruning. Functionally, it is how the Conduit turns accumulated experience into identity.

### 10.2 When it runs

- Scheduled cron-style at `DREAM_SCHEDULE` (default `0 3 * * *` — 3 AM local). Fixed schedule, not idle-triggered.
- Requires `DREAM_MIN_NEW_DURABLE` new durable memories since the last dream (default 5). If too little has happened, the dream is skipped — nothing to consolidate.
- Only one dream runs at a time. If the window expires with the pass still running, it is truncated cleanly (see 10.5).

### 10.3 Phases

A dream pass runs in ordered phases, each with its own budget:

**Phase 1 — Pattern extraction.** Walks REGRETs and ACCOMPLISHMENTs added since the last dream. Clusters them by `intent_at_time`, surprise-delta distribution, and outcome. Emits candidate patterns ("routings to Artificer under constraint X fail 4/5 times").

**Phase 2 — WISDOM candidacy.** For each pattern with ≥ `WISDOM_N` supporting memories (default 5) and a consistent self-invariant, mints a **pending** WISDOM candidate. Pending candidates live in a separate staging table; they are not visible to routing retrieval.

**Phase 3 — Affirmation proposal.** For patterns where the self-invariant suggests a forward commitment ("I should default to Scribe for writing-tinged ambiguity"), mints a pending AFFIRMATION proposal.

**Phase 4 — Lesson consolidation.** Pairs of contradicting OPINIONs / LESSONs whose resolution is now clear get collapsed: a new LESSON is minted that supersedes both, with `supersedes` listing the lineage.

**Phase 5 — Pruning (non-durable only).** Below-threshold OBSERVATIONs and HYPOTHESISes that haven't been reinforced in `DREAM_PRUNE_HORIZON` (default 30 days) have their weights decayed further, and those that drop below `MIN_RETAIN_WEIGHT` are soft-deleted. Durable tiers are **never touched in this phase**.

**Phase 6 — Review gate.** Pending WISDOM and AFFIRMATION candidates go through a review:

- In Project Turing's research mode: automatic, with a self-consistency check that the candidate doesn't contradict existing WISDOM.
- In any future `main` port: operator-reviewed.

Candidates that pass review are committed to the durable store with `origin_episode_id` linking to the dream session marker. Candidates that fail are logged and retained in staging for operator inspection (not merged, not lost).

**Phase 7 — Marker.** A single `OBSERVATION` / `I_DID` memory is written recording that a dream session ran, its duration, phase-level counts, and pointers to committed and rejected candidates. The Conduit remembers its own dreams.

### 10.4 Bounds

- **Wall-clock budget.** `DREAM_MAX_DURATION` (default 30 minutes). If exceeded, phases not yet started are skipped.
- **Token budget.** `DREAM_TOKENS_PER_SESSION` (default 200,000). Phases that run out of tokens halt cleanly.
- **Candidate cap.** `DREAM_MAX_WISDOM_CANDIDATES` (default 3). Dreaming cannot flood the WISDOM tier in a single pass.
- **No concurrent requests during phase 4/5.** These touch existing memory rows. Write lock held for their duration; request handling continues against a read-only snapshot.

### 10.5 Failure semantics

Dreaming is transactional per phase. A crash, OOM, or timeout:

- Discards any pending candidates that were not yet committed.
- Leaves already-committed candidates in place (they are `immutable=True` if WISDOM).
- Writes a partial-session marker recording how far the pass got.
- Does not retry automatically. The next scheduled dream picks up with the accumulated memory state.

### 10.6 Provenance of dream-origin WISDOM

A WISDOM memory minted from dreaming is `source = I_DID` because its content is distilled from I_DID REGRETs and ACCOMPLISHMENTs. The **act of dreaming** is an I_DID action by the Conduit; the **content** is derived from I_DID experience. This preserves the provenance lock (INV-3) while allowing consolidation to produce durable memory.

The `context` field on a dream-origin WISDOM memory must list every contributing memory_id; that list is structurally part of the memory. A WISDOM entry without traceable I_DID lineage is rejected at the repository boundary.

---

## 11. Migration and persistence

### 11.1 Storage

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

### 11.2 Version migration

Any migration that touches `durable_memory` must:

1. Preserve every row. CI check asserts `SELECT COUNT(*)` before and after migration is monotonic-non-decreasing.
2. Preserve every `self_id`. No migration may remap existing self_ids; new ones can be minted.
3. Preserve every row's `tier` and `source`. Tier upgrades are new rows with `supersedes`, never in-place updates.
4. Emit a migration-report row into the durable store itself: `tier=OBSERVATION`, `source=I_DID`, `content="migration <version> applied"`. The Conduit remembers its own upgrades.

### 11.3 self_id minting

`self_id` is assigned once, at the first bootstrap of a Conduit instance, and stored in a dedicated `self_identity` table separate from per-deployment config. Redeployment reads the existing `self_id`; only a clean-slate bootstrap (explicit operator command) may mint a new one, and doing so archives the old.

---

## 12. Open questions

1. **WISDOM consolidation policy.** What's the right N for "pattern across N memories"? Too low and WISDOM inflates; too high and the pipeline never consolidates. Probably starts at 5 and gets tuned from observation data.
2. **Affect scale calibration.** `affect ∈ [-1.0, 1.0]` needs a stable mapping from outcome signals (error rate, user correction, downstream success) to a scalar. Open.
3. **ACCOMPLISHMENT threshold drift.** If the surprise_delta threshold is fixed, the pipeline stops minting ACCOMPLISHMENTs as it gets better at its job — success stops being surprising. Does the threshold need to adapt, or does that defeat the point?
4. **Revocable AFFIRMATION vs accumulated LESSONs.** If a commitment is repeatedly superseded, should the lineage be consolidated into a LESSON (or REGRET) about the pattern of commitment-failures?
5. **Multi-instance Conduit.** If a horizontally-scaled deployment runs multiple Conduit processes, do they share a `self_id` and therefore share durable memory? Probably yes for the research model; but this is where the near-fork meets practical infra.
6. **Adversarial provenance.** Even with `source=I_DID` locked, a prompt-injected tool result could cause the Conduit to *believe* it did something it didn't. The `I_DID` guarantee is only as strong as the pipeline's grounding of "my actions." What's the minimum audit trail that makes provenance verifiable?
7. **Interaction with `main`'s audit log.** `main` already has an `AuditLog`. Is the durable memory store a superset, a sibling, or a consumer of AuditLog events? Answering this matters the moment any of this even conceptually returns to `src/`.
8. **Daydream seed bias.** Seeding preferentially on unresolved REGRETs risks the pipeline spending its idle compute on rumination. Should there be a counter-weight toward ACCOMPLISHMENT seeds, or toward neutral OBSERVATION exploration? Tuning knob, with risk either way.
9. **Dream-skip vs dream-always.** Skipping when too little new durable material has accumulated is efficient but breaks periodic self-check — the Conduit never pauses to examine itself unless there's "enough" material. Competing intuition: sometimes self-examination should happen because it's been a while, not because there's news.
10. **Daydream→live contamination.** AC-11/12 prevent daydream writes to durable tiers, and retrieval defaults exclude I_IMAGINED. But retrieval patterns used in daydream prospection could subtly shape what the pipeline *notices* in live operation — exposure effects. Is there an instrumentation story that measures whether daydream patterns are biasing live routing, and what the threshold for concern is?
11. **Dream-origin WISDOM vs direct experience.** A WISDOM entry from dreaming has I_DID provenance through its context lineage, but the pattern-extraction step is LLM-mediated. How do we distinguish, at retrieval time, a WISDOM that arose from direct pattern observation vs one that was the LLM's pattern-proposal during a dream? Likely a `consolidation_path` enum field on WISDOM.
