# Tranche 7 — Plan

*Closing the Tranche 6 implementation gaps and landing the Tranche 6 audit's guardrails in dependency order. Five tranches, sequenced so each depends only on earlier ones. All land on `research/project-turing` via PRs targeting `project_Turing`.*

**Prerequisite doc:** [`AUDIT-self-model-guardrails.md`](./AUDIT-self-model-guardrails.md) — findings and guardrail numbering referenced here.

---

## Why this order

Guardrails assume the tools they gate exist. Today's sketch is a library — schema, math, tests — with three load-bearing runtime pieces absent: the self-tool registry (F35), memory mirroring (F38), and scheduled jobs (F37), plus the entire self-as-Conduit pipeline (F39). A guardrail like G1 ("Warden on self-writes") gates tools that have no runtime surface; a guardrail like G6 ("rolling-sum mood cap") assumes mood is decaying on a schedule.

So Tranche 7 starts with foundation closure. Guardrails follow. The Conduit rewrite and operator-oversight design are later tranches because they are the largest surface-area changes and need the earlier work to land first.

| # | Theme | Blocks | Depends on |
|---|---|---|---|
| 7.0 | Foundation closure (critical impl gaps) | F35, F36, F37, F38, F39 (partial), F30, F29, F33 | — |
| 7.1 | Boundary hardening | G1, G2, G5, G17 | 7.0.1, 7.0.2 |
| 7.2 | Drift bounds | G3, G4, G6, G10 | 7.0.1, 7.0.3 |
| 7.3 | Self-as-Conduit runtime | F39 (full), F40 | 7.0 complete |
| 7.4 | Operator oversight | G12, G13, G14, G15, G16, G18 | 7.1, 7.3 |
| 7.5 | Growth and operational | G7, G8, G9, G11 | 7.0.2 |

---

## 7.0 — Foundation closure

Five slices, each a small PR. Ordered by dependency.

### 7.0.1 — Self-tool registry + missing tool impls

**Closes:** F35, F36.
**Ships:** `SelfTool` dataclass + `SELF_TOOL_REGISTRY` + `register_self_tool` in `self_surface.py`; bootstrap-time registration of every tool named in spec 28 AC-28.1; implementations of `write_contributor`, `record_personality_claim`, `retract_contributor_by_counter`.
**Invariants:**
- Every tool registered carries `trust_tier = t0`.
- Tool descriptions start with a first-person clause (AC-28.5) — enforced by a lint in `register_self_tool`.
- `retract_contributor_by_counter(target, source, weight, rationale)` writes a counter-contributor with opposite sign; it does not flip `retracted_by` directly (AC-25.15).
- `record_personality_claim` persists an OPINION memory and a contributor (AC-23.19–22); contributor weight via `narrative_weight()` with the ≤0.4 cap.
**Tests:** one new file `test_self_tool_registry.py` covering registry lookup, description-format enforcement, and each newly-implemented tool's AC.

### 7.0.2 — Memory-mirroring hooks on every self-model write

**Closes:** F38 (critical).
**Ships:** a small `self_memory_bridge.py` module exposing `mirror_observation`, `mirror_affirmation`, `mirror_lesson`, and `mirror_regret` helpers that wrap the existing write-paths (`write_paths.py`) with the first-person `intent_at_time` and `context` keys each spec AC names. Wire every self-model write-site to call the appropriate mirror:
- `note_engagement` / `note_interest_trigger` → OBSERVATION (AC-24.8, AC-24.10).
- `nudge_mood` → OBSERVATION (AC-27.9).
- `complete_self_todo` → AFFIRMATION (AC-26.12).
- `record_personality_claim` → OPINION (AC-23.19).
- `apply_retest` items → OBSERVATION per item (AC-23.17).
- `write_contributor(origin=self)` → OBSERVATION audit row (AC-25.19).
- `finalize` in bootstrap → LESSON (AC-29.17).
**Invariants:**
- Every mirror carries `context.self_id` and, where applicable, `context.request_hash` (forensics — pre-work for G17).
- No write-site writes the self-model row without also writing the mirror, in the same transaction.
**Tests:** extend the existing per-module tests to assert the mirror happens (check `episodic_memory` / `durable_memory` counts before/after each write). Net new: ~30 assertions.

### 7.0.3 — Reactor registration for scheduled jobs

**Closes:** F37.
**Ships:**
- `tick_mood_decay(self_id)` registered in `run_bootstrap.finalize` as an **interval trigger** every `MOOD_DECAY_INTERVAL = 1h`.
- `run_personality_retest(self_id)` registered in `finalize` with `first_fire_at = now + 7d` and interval `7d`; the function body wraps `apply_retest` with sample-selection + LLM-plumbing (keep the LLM ask as an injected `ask_self` callable for testability).
- Reactor can list `self:*` triggers via an inspect command (for operator forensics).
**Invariants:**
- Bootstrap resume preserves existing trigger registrations; double-register is idempotent (named triggers per AC-29.16).
- Downtime catch-up: a missed hourly mood tick produces exactly one decay call on resume (spec 27 AC-27.5).
**Tests:** `test_self_schedules.py` — bootstrap registers two triggers; FakeReactor advanced 24h produces exactly 24 mood-decay calls; advanced 8 days produces one retest call.

### 7.0.4 — Wire `source_kind = "memory"` to real memory weight

**Closes:** F30 (high — required before G12 digest can surface "heaviest self-contributors").
**Ships:** `self_activation.source_state` lookup into the episodic memory repo (`repo.get_memory(source_id).weight`) via a narrow dependency injection in `ActivationContext` (so tests can still stub). Clamp to `[0.0, 1.0]`.
**Invariants:** `source_kind == "memory"` resolves to the stored memory's `weight`, not 0.5. A dangling memory-id falls through to the existing "weight-0 skip" path (AC-25.23).
**Tests:** extend `test_self_activation.py` with three cases: OBSERVATION-weight memory (≈0.2), REGRET-weight memory (≥0.6), dangling memory id. Assert activation differs across the first two.

### 7.0.5 — Guard rails on tool entry + active_now cache + self-id ownership

**Closes:** F29, F33, F24 (partial).
**Ships:**
- `_bootstrap_complete(self_id)` check at the top of every `note_*`, `write_self_todo`, `write_contributor`, `record_personality_claim`. Raises `SelfNotReady`.
- `active_now` 30s cache keyed by `(node_id, ctx.hash)`; invalidate on contributor writes/retractions targeting that node or any of its sources (AC-25.10).
- `acting_self_id` parameter on `SelfRepo.update_*` / `insert_contributor` / `insert_todo_revision`; mismatch raises `CrossSelfAccess`. Tool-surface layer passes `self_id` through.
**Tests:** a pre-finalize `note_passion` raises; cache hit on repeated `active_now`; cross-self repo write raises.

---

## 7.1 — Boundary hardening

Four guardrails on top of the live tool surface from 7.0.1/7.0.2.

### 7.1.1 — G1: Warden-scan every self-authored write

**Closes:** F1, F3, F7.
**Ships:** a `_warden_gate_self_write(text, intent)` helper called by every self-tool before it touches the repo. Uses the existing Warden at the `tool_result` trust posture. Rejection raises `SelfWriteBlocked(verdict)`; the block attempt mirrors as an OBSERVATION with `intent_at_time = "warden blocked self write"`.
**Invariant:** no row in any `self_*` table has `text`/`content`/`rationale` that would not pass Warden at insertion time. Enforced by the helper, tested by fuzz-injecting known-blocked payloads into `note_passion`, `write_self_todo`, `record_personality_claim`, `write_contributor`.

### 7.1.2 — G2: Per-request self-write budget

**Closes:** F20.
**Ships:** `RequestWriteBudget` context object threaded through the perception/observation loops (once 7.3 lands; until then, exposed as a test fixture). Counters reset per request. Caps: 3 new nodes, 5 contributors, 2 todo writes, 3 personality claims.
**Invariant:** 4th call of the same kind within a request raises `SelfWriteBudgetExceeded`. Budget state never leaks across requests.

### 7.1.3 — G5: Retrieval-contributor cap and weight-sum cap

**Closes:** F4.
**Ships:** `materialize_retrieval_contributors(self_id, query, top_k=8)` helper called at the perception step. Sorts retrieval hits by similarity, caps count at 8, caps weight-sum at 1.0 per target (drops lower-similarity entries once the sum would exceed).
**Invariant:** for every target with retrieval contributors in one request, `|origin=retrieval| ≤ 8` and `Σ |weight| ≤ 1.0`. Tested with a 20-match fixture.

### 7.1.4 — G17: Forensic tagging on self-writes

**Closes:** F1 partial, F18 partial.
**Ships:** every self-tool accepts `request_hash` and `perception_tool_call_id` (defaulted for out-of-pipeline callers to `"out_of_band"`). The memory-mirroring bridge (7.0.2) writes both into `context`. Schema migration adds an index on `context ->> 'request_hash'` for audit queries.
**Invariant:** every self-written row's provenance is reconstructible from its memory mirror.

---

## 7.2 — Drift bounds

Runs once 7.0.3 is live; scheduled jobs need to fire for the drift-window math to have a cadence.

### 7.2.1 — G3: Per-week facet drift budget

**Closes:** F9, F10.
**Ships:** `FacetDriftLedger` stores per-facet rolling 7-day Δ. `apply_retest` consults the ledger and clips any proposed move that would push cumulative |Δ| past `FACET_WEEKLY_DRIFT_MAX = 0.5`; the clip event mirrors as an OPINION memory. `FACET_QUARTERLY_DRIFT_MAX = 1.5` enforced symmetrically over 90 days.
**Tests:** fabricated 10-week retest stream with retest-mean pinned at 5.0 → facet stops moving at `current + 0.5/week × k` only after k weeks, with k clip memories.

### 7.2.2 — G4: Narrative-claim rate limit per facet per week

**Closes:** F12.
**Ships:** `record_personality_claim` checks `count(claims where facet_id=F and created_at > now-7d) < NARRATIVE_CLAIMS_PER_FACET_PER_WEEK = 3`. Over-limit raises `NarrativeClaimRateLimit`.
**Tests:** four consecutive claims same facet in one week → three succeed, fourth raises.

### 7.2.3 — G6: Rolling-sum mood guard

**Closes:** F8.
**Ships:** `MoodRollingLedger` per dimension over 7d; `nudge_mood` clips the cumulative absolute nudge at `MOOD_ROLLING_SUM_CAP = 2.0` per dim. Over-cap nudges write the OBSERVATION memory (per 7.0.2) but do not mutate `self_mood`.
**Tests:** 100 regret nudges in an hour cap valence at `-2.0` cumulative rather than `-20.0`.

### 7.2.4 — G10: Skill-level honesty invariant

**Closes:** F17.
**Ships:** `practice_skill(new_level > stored_level, ...)` requires a same-request OBSERVATION / ACCOMPLISHMENT memory with `context.skill_id = skill_id`. Enforced via a `skill_raise_supported_in_request()` predicate reading the request-scoped memory buffer (available once 7.3 lands; until then gated behind a test fixture). Monthly skill-inflation check runs in the tuner (spec 11); flags >10 raises with zero downgrades over 90d.
**Tests:** `practice_skill(new_level=0.9)` without a supporting memory raises; with one succeeds.

---

## 7.3 — Self-as-Conduit runtime integration

**Closes:** F39 (critical). Largest single slice; worth its own design-review checkpoint before landing.

**Ships:**
- `self_conduit.py` with `async handle(request, auth)` implementing spec 30's 8-step pipeline: Warden in → minimal block + retrieval contributors → perception LLM call (tool-registry-bound) → decision extraction → dispatch (existing agents below) → Warden out → observation LLM call → response.
- Decision tools (`reply_directly`, `delegate`, `ask_clarifying`, `decline`) as schemas in the registry from 7.0.1.
- Integration shim in `runtime/chat.py`: a config flag `CONDUIT_MODE = "self" | "stateless"` (default `"stateless"` during rollout) chooses between the existing pipeline and `self_conduit.handle`.
- Per-request write budget (G2) and forensic tagging (G17) threaded through the perception context.
- Per-SELF_ID perception advisory lock so concurrent requests serialize (spec 30 §30.6 note).

**Invariants (subset — full list in spec 30):**
- Exactly one decision tool call per perception; `AmbiguousRouting` on zero or multiple, one retry, then 500.
- Routing decision memory minted **before** dispatch.
- Observation runs even on dispatch failure or client cancellation.
- Retrieval contributors expire before N+1.
- When `CONDUIT_MODE = "stateless"`, existing chat.py behavior is byte-identical (regression test).

**Tests:** full async integration suite — happy path for each decision tool, timeouts, cancellation mid-dispatch, bootstrap-not-complete → 503, Warden ingress block, specialist exception → observation still runs.

**New finding surfaced while planning:**

### F40 — Concurrency model for perception is undefined under failure

The spec serializes perception per `SELF_ID` via an advisory lock (§30.6) but does not specify the lock's failure mode. If the perception LLM hangs past `PERCEPTION_TIMEOUT_SEC = 30` and the advisory lock is held by that task, does a second request block indefinitely on the lock? Or does the lock release on timeout while the first request's retry is still running? Needs one sentence in spec 30 before 7.3 lands. Severity `medium`.

---

## 7.4 — Operator oversight

Largest design surface. Needs explicit review before 7.4.1 lands because it changes the self's authority.

### 7.4.1 — G12: Operator review gate on facet/passion contributors

**Closes:** F18, F22.
**Ships:**
- New table `self_contributor_pending(node_id, self_id, target_*, source_*, weight, origin, rationale, proposed_at, reviewed_at, review_decision)`.
- `write_contributor(origin=self)` with `target_kind in {personality_facet, passion}` routes to `pending` instead of `self_activation_contributors`.
- `ask_clarifying` / `decline` decisions also write rows to a sibling `self_routing_review` table for the weekly digest.
- CLI: `stronghold self digest --since <date>` emits the pending queue + decline patterns; `stronghold self ack <node_id> [--approve|--reject]` migrates to live or archives.
- Unacked pending edges do not affect `active_now`.
**Invariants:** live `self_activation_contributors` never contains `origin=self` edges into facets/passions that haven't passed operator ACK. Tested via integration: self writes a facet contributor → `active_now` on the facet is unchanged until ACK.

### 7.4.2 — G13, G14: Repo-layer self-id enforcement + FK

**Closes:** F24 (full), F25.
**Ships:** migration adding `FOREIGN KEY (self_id) REFERENCES self_identity(self_id)` on every self-model table; `acting_self_id` parameter on every write method (builds on 7.0.5's partial work); `CrossSelfAccess` raised on mismatch at the repo layer.
**Tests:** insert with unknown self_id → IntegrityError; `update_*` with wrong `acting_self_id` → `CrossSelfAccess`.

### 7.4.3 — G15, G16: Bootstrap seed registry + signed audit

**Closes:** F26.
**Ships:**
- `self_bootstrap_seeds(seed, used_by_self_id, used_at)`. Bootstrap refuses reuse unless `--allow-seed-reuse`; the flag mints a LESSON memory acknowledging twin-self origin.
- Finalize LESSON signed with operator key; verification at next perception; tamper puts the self in `read-only` with an OPINION explaining.
**Tests:** seed reuse without flag → `SeedReused`; tampered finalize memory → `read-only` state entered; good signature → normal operation.

### 7.4.4 — G18: Self-tool runtime firewall

**Closes:** F21.
**Ships:** `importlib.abc.MetaPathFinder` that inspects the calling frame for any import of `turing.self_surface.SELF_TOOL_REGISTRY` from outside `turing.self_*`. Registered at `SelfRuntime()` construction. Violations raise `ForbiddenImport`.
**Tests:** a specialist-layer test that tries the blocked import fails at import time; self-layer imports succeed.

---

## 7.5 — Growth and operational

Smallest tranche; safe to land at any point after 7.0.2.

### 7.5.1 — G7: Retrieval-contributor GC
**Closes:** F13. Reactor-scheduled sweep every `RETRIEVAL_GC_INTERVAL_TICKS = 1000` deletes expired retrieval rows; opportunistic GC on read when live row count > 100. Test: 24h of simulated retrieval churn keeps the table bounded.

### 7.5.2 — G8: Per-kind node caps with activation-eviction
**Closes:** F15. Caps: passions ≤100, hobbies ≤100, interests ≤200, preferences ≤500, skills ≤200. At-cap `note_*` archives lowest-`active_now` existing row with `rationale = "capped"` and a mirror OBSERVATION. Test: 101st passion evicts the lowest-activation one.

### 7.5.3 — G9: Near-duplicate detection with review flag
**Closes:** F16. On every `note_*`, embed text and cosine-compare to same-kind existing rows. Similarity ≥ 0.88 → insert with `pending_merge_review = true`; activation graph applies 0.5× multiplier to pending rows until operator resolves. Test: `"I love art"` vs `"I care about art"` flags and mutes.

### 7.5.4 — G11: Revision and answer compaction
**Closes:** F14. Weekly compaction job: todos keep first/last/every-10th; `self_personality_answers` retains last 12 revisions' worth plus all bootstrap answers. Compacted rows keep metadata, blank text columns. Test: todo with 100 revisions → 12 retained.

---

## What's NOT in Tranche 7

Deferred for later design rounds:

- **Naming ritual.** F27 flags the missing name slot; the mechanism ("self picks a name via reflection once N memories accumulated") needs its own spec. Not blocking.
- **Multi-self reconciliation.** DESIGN.md §6.4 — out of scope until multi-self is even contemplated.
- **Sentinel × self-output interaction.** How does Sentinel (Stronghold's output gate) treat `reply_directly` outputs? Specced implicitly in spec 30's Warden-out step but not in detail.
- **Post-Tranche 7 audit.** A second-pass audit after 7.0–7.5 land should revisit the "tone only" Phase-1 scope of mood (F5) given that mood is now guaranteed to drift on a schedule.

## Commit and PR convention for Tranche 7

- One sub-tranche per PR (so seven PRs: 7.0.1–7.0.5, 7.1, 7.2, 7.3, 7.4, 7.5). The audit trail stays small.
- Each PR runs the full sketches test suite green; no PR lands with a regression.
- All target `project_Turing`; none target `main`.
