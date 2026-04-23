# Project Turing — Specs

Individually reviewable specs for the durable personal memory layer. Each spec owns its acceptance criteria and its implementation guidance. Specs are small on purpose; a reviewer should be able to hold one in mind at once.

**Branch:** `research/project-turing` (research only; not for `main`).
**Parent doc:** [`../DESIGN.md`](../DESIGN.md).

---

## Specs in this directory

Read in order. Later specs depend on earlier ones.

### Memory layer (Tranche 1 — buildable today)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 1 | [`schema.md`](./schema.md) | Field additions to `EpisodicMemory`; the `SourceKind` enum. | — |
| 2 | [`tiers.md`](./tiers.md) | Add `ACCOMPLISHMENT`. Revised 8-tier set with weight bounds and inheritance priority. | 1 |
| 3 | [`durability-invariants.md`](./durability-invariants.md) | The eight invariants enforced for REGRET, ACCOMPLISHMENT, WISDOM. | 1, 2 |
| 4 | [`write-paths.md`](./write-paths.md) | Write triggers and actions for REGRET, ACCOMPLISHMENT, AFFIRMATION. | 1, 2, 3 |
| 5 | [`wisdom-write-path.md`](./wisdom-write-path.md) | WISDOM invariants (consolidation-origin only, I_DID provenance, traceable lineage, no superseding WISDOM). Write path defined in `dreaming.md`. | 1, 2, 3, 12 |
| 6 | [`retrieval.md`](./retrieval.md) | Reserved quota, source-filtered views, lineage-aware retrieval. | 1, 2, 3 |
| 8 | [`persistence.md`](./persistence.md) | `durable_memory` table, version migration, `self_id` minting. | 1, 2, 3 |

### Motivation and dispatch (Tranche 2 — needs scheduling primitive)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 9 | [`motivation.md`](./motivation.md) | Priority ladder (P0=1M … P70=0.01), pressure vector, fit vector, scoring formula, backlog, two loops, dispatch contract. | 1, 2, 3, 4 |
| 10 | [`scheduler.md`](./scheduler.md) | P0 scheduled-delivery work. Early-executable window, held-for-delivery, 5x-dream-time quiet zones. | 9 |
| 7 | [`daydreaming.md`](./daydreaming.md) | Per-model candidate producer of last resort. I_IMAGINED writes only; cannot reach durable tiers. Priority is f(pressure). | 1, 2, 3, 6, 9 |

### Tuning and detectors (Tranche 3 — observation feed + first detector)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 11 | [`tuning.md`](./tuning.md) | Runtime coefficient adjustment. Observations → tuner candidates → AFFIRMATION commitments. | 1, 4, 9 |
| D | [`detectors/README.md`](./detectors/README.md) | Detector pattern: cheap watchers that propose backlog candidates. | 9 |
| D.1 | [`detectors/contradiction.md`](./detectors/contradiction.md) | Worked example — detects contradictory durable memories with a known resolution; proposes a LESSON-minting candidate. | 1, 3, 4, 9, D |

### Dreaming (Tranche 4 — consolidation and WISDOM)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 12 | [`dreaming.md`](./dreaming.md) | Scheduled consolidation. Seven phases: pattern extraction, WISDOM candidacy, AFFIRMATION proposal, LESSON consolidation, non-durable pruning, review gate, session marker. Sole write path into WISDOM tier. | 1, 2, 3, 4, 9, 10 |

### Runtime + integration (Tranche 5 — built directly; specced retroactively)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 13 | [`journal.md`](./journal.md) | Multi-resolution narrative: today / yesterday / week / month / recent-history. Progressive LLM summarization at each level. Identity refresh on WISDOM change. | 1, 8 |
| 14 | [`working-memory.md`](./working-memory.md) | Operator base prompt (immutable to self) + self-managed working memory (bounded scratch space). WM maintenance loop is a P13 RASO producer. | 1, 8, 9 |
| 15 | [`rss-thinking.md`](./rss-thinking.md) | Four progressive levels per RSS item: weak summary always, WM entry on notable, OPINION on interesting, AFFIRMATION + scheduled action on commit. | 1, 2, 4, 9, 14, 18 |
| 16 | [`semantic-retrieval.md`](./semantic-retrieval.md) | Embedding-based search across durable + stance-bearing memory. Score = similarity × weight. I_DID-only by default. | 1, 6, 8, 19 |
| 17 | [`chat-surface.md`](./chat-surface.md) | OpenAI-compatible HTTP. Streaming for plain replies, non-streaming when tools fire. Per-user session tagging via upstream auth header. Cluster does auth. | 9, 14, 16, 18, 19 |
| 18 | [`tool-layer.md`](./tool-layer.md) | ToolRegistry allowlist, OpenAI function-call schemas, failure → stance OPINION. Obsidian + RSSReader real; Wiki/WP/Search/Newsletter scaffolded. | 1, 4, 17 |
| 19 | [`litellm-provider.md`](./litellm-provider.md) | Single LiteLLM proxy + virtual key. Pools = (model, free-tier window, role). complete + embed + quota_window in one Provider Protocol. | 8 |
| 20 | [`runtime-reactor.md`](./runtime-reactor.md) | Blocking-tick + ThreadPoolExecutor side channel. Deliberate divergence from main's asyncio. FakeReactor for tests. | — |
| 21 | [`observability.md`](./observability.md) | v1 Prometheus metric contract. Inspect CLI read-only subcommands. Smoke mode acceptance criteria. | all |

### Self-model (Tranche 6 — durable content of the autonoetic self)

The self-model — what the Turing Conduit knows about itself between requests — above and beyond episodic memory. Companion overview at [`../autonoetic-self.md`](../autonoetic-self.md).

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 22 | [`self-schema.md`](./self-schema.md) | Tables and value types for all self-model nodes: personality facets, passions, hobbies, interests, preferences, skills, todos, mood, activation contributors. | 1, 2 |
| 23 | [`personality.md`](./personality.md) | HEXACO-24 profile. Random bootstrap draw, 200-item HEXACO-PI-R seed, weekly 20-item re-test weighted by time-since-last-asked, narrative revision via the activation graph. | 22 |
| 24 | [`self-nodes.md`](./self-nodes.md) | Passions, hobbies, interests, preferences, skills. Bootstrap-empty, accrete via self-authored `note_*` tools. Skill decay applied on read: `level × exp(-rate × days)`. | 22 |
| 25 | [`activation-graph.md`](./activation-graph.md) | Contributor edges (`target, source, weight, origin, rationale`). `active_now(node) = sigmoid(Σ weight × source_state / SCALE)`. Origins: self / rule / retrieval (TTL-bounded). Conflict via counter-contributors. | 22, 23, 24 |
| 26 | [`self-todos.md`](./self-todos.md) | Self-authored todos with required `motivated_by_node_id`. Append-only revision history. Completion mints AFFIRMATION + reinforces motivator via a contributor edge. | 22, 24 |
| 27 | [`mood.md`](./mood.md) | `(valence, arousal, focus)` singleton. Hourly decay toward neutral; event nudges (tool success/fail, AFFIRMATION/REGRET mints, todo completion, Warden alerts). Phase-1: affects tone only. | 22, 2 |
| 28 | [`self-surface.md`](./self-surface.md) | Self-tool registry, `recall_self()` deep read, 4-line minimal prompt block (identity + mood + active todos + dominant passion). First-person framing throughout. | 22, 23, 24, 25, 26, 27 |
| 29 | [`self-bootstrap.md`](./self-bootstrap.md) | `stronghold bootstrap-self` CLI. Random HEXACO draw → 200 Likert LLM answers with justifications → 24 facets + 1 mood + empty everything else. Idempotent per `self_id`; resumable. | 22, 23, 24, 27, 8 |
| 30 | [`self-as-conduit.md`](./self-as-conduit.md) | First-person routing pipeline: Warden → minimal block + retrieval contributors → perception (LLM + possible `recall_self`) → decision (`reply_directly` / `delegate` / `ask_clarifying` / `decline`) → dispatch → observation (self-model updates, mood nudges). Replaces the stateless Conduit for the Turing branch. | 22, 23, 24, 25, 26, 27, 28, 29, 9, 16, 17 |

### Tranche 7 (planning — not yet implemented)

Closes Tranche 6 implementation gaps and lands the audit's guardrails in dependency order. Plan doc: [`../PLAN-tranche-7.md`](../PLAN-tranche-7.md). Audit: [`../AUDIT-self-model-guardrails.md`](../AUDIT-self-model-guardrails.md).

**7.0 — Foundation closure** (critical impl gaps from F35–F39)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 31 | [`self-tool-registry.md`](./self-tool-registry.md) | `SelfTool` dataclass + `SELF_TOOL_REGISTRY` + `register_self_tool`; implementations of `write_contributor`, `record_personality_claim`, `retract_contributor_by_counter`. | 28, 18 |
| 32 | [`memory-mirroring.md`](./memory-mirroring.md) | `self_memory_bridge.py` wraps write-paths for every self-model write-site; closes ~10 spec ACs that specified memory mirrors but were silently ignored. | 1, 2, 4, 31 |
| 33 | [`self-schedules.md`](./self-schedules.md) | Reactor interval triggers for `tick_mood_decay` (hourly) and `run_personality_retest` (weekly), registered at bootstrap finalize. | 20, 27, 23, 29, 32 |
| 34 | [`memory-source-state.md`](./memory-source-state.md) | Wire `source_kind = "memory"` to real `memory.weight`; restore "REGRET > OBSERVATION" invariant in activation graph. | 1, 2, 25, 8 |
| 35 | [`self-write-preconditions.md`](./self-write-preconditions.md) | Bootstrap-complete check on every write-tool; `active_now` 30s cache with invalidation; `acting_self_id` on repo mutators. | 22, 29, 28, 25 |

**7.1 — Boundary hardening** (guardrails G1, G2, G5, G17)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 36 | [`warden-on-self-writes.md`](./warden-on-self-writes.md) | Warden scan (tool-result posture) on every self-authored text write; block mirrors as OBSERVATION. | 31, 32 |
| 37 | [`self-write-budgets.md`](./self-write-budgets.md) | Per-request caps: 3 new nodes / 5 contributors / 2 todo-writes / 3 personality claims. | 31, 35 |
| 38 | [`retrieval-contributor-cap.md`](./retrieval-contributor-cap.md) | Top-K ≤ 8 retrieval contributors per target; Σ\|weight\| ≤ 1.0 per target per request. | 25, 16, 44 |
| 39 | [`forensic-tagging.md`](./forensic-tagging.md) | `request_hash` + `perception_tool_call_id` context vars stamp every self-write via the memory bridge. | 32, 31, 44 |

**7.2 — Drift bounds** (G3, G4, G6, G10)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 40 | [`facet-drift-budget.md`](./facet-drift-budget.md) | Rolling 7-day and 90-day Δ caps per facet; `apply_retest` clips; OPINION memory on clip. | 23, 33, 32 |
| 41 | [`narrative-claim-rate-limit.md`](./narrative-claim-rate-limit.md) | ≤ 3 `record_personality_claim` per facet per rolling 7 days. | 23, 31, 32 |
| 42 | [`mood-rolling-sum-guard.md`](./mood-rolling-sum-guard.md) | Cap cumulative \|delta\| per mood dim per rolling 7 days; over-cap still mirrors, doesn't mutate. | 27, 33, 32 |
| 43 | [`skill-honesty-invariant.md`](./skill-honesty-invariant.md) | `practice_skill(new_level > stored_level)` requires a same-request supporting OBSERVATION/ACCOMPLISHMENT. | 24, 32, 39 |

**7.3 — Self-as-Conduit runtime** (closes F39, F40)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 44 | [`conduit-runtime.md`](./conduit-runtime.md) | Implementation of spec 30's full perception → decision → dispatch → observation pipeline. Per-self advisory lock with watchdog. | 30, 31, 32, 33, 35, 37, 38, 39, 17, 36 |
| 45 | [`conduit-mode-shim.md`](./conduit-mode-shim.md) | `CONDUIT_MODE = "stateless" \| "self"` config flag; default stateless during rollout. | 44, 17 |

**7.4 — Operator oversight** (G12, G13, G14, G15, G16, G18)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 46 | [`operator-review-gate.md`](./operator-review-gate.md) | Self-authored facet/passion contributors route to `self_contributor_pending`; weekly digest + CLI ack. | 25, 31, 32, 39 |
| 47 | [`repo-self-id-enforcement.md`](./repo-self-id-enforcement.md) | `acting_self_id` parameter on every `SelfRepo` mutator; FK from every self-model table to `self_identity`. | 22, 8, 35 |
| 48 | [`bootstrap-seed-registry.md`](./bootstrap-seed-registry.md) | Refuse reused HEXACO seeds by default; sign bootstrap-complete memory with operator HMAC; tamper → read-only mode. | 29, 8, 32 |
| 49 | [`self-tool-import-firewall.md`](./self-tool-import-firewall.md) | `importlib` meta-path finder blocks imports of `SELF_TOOL_REGISTRY` from non-self modules. | 31 |

**7.5 — Growth and operational** (G7, G8, G9, G11)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 50 | [`retrieval-contributor-gc.md`](./retrieval-contributor-gc.md) | Scheduled sweep + opportunistic-on-read GC of expired retrieval contributors. | 25, 20, 33 |
| 51 | [`per-kind-node-caps.md`](./per-kind-node-caps.md) | Hard caps per kind; at-cap `note_*` archives lowest-`active_now` existing row. | 24, 25, 32, 35 |
| 52 | [`near-duplicate-review.md`](./near-duplicate-review.md) | Cosine-similar `note_*` texts flag for merge-review; 0.5× activation multiplier until operator resolves. | 24, 16, 46, 32 |
| 53 | [`revision-compaction.md`](./revision-compaction.md) | Weekly compaction of `self_todo_revisions` and `self_personality_answers`. | 26, 23, 20 |
### Autonoetic completion (Tranche 7 — Phase 2)

| # | Spec | Scope | Depends on |
|---|-------|--------|------------|
| 31 | [`source-monitoring.md`](./source-monitoring.md) | First-person validation at write boundary, perspective reconstruction, stance owner enforcement. Closes DESIGN §4.1 + §4.4. | 1, 22 |
| 32 | [`memory-source-state.md`](./memory-source-state.md) | Wire episodic/durable memory weights into activation graph source_state. Closes F30. | 25 |
| 33 | [`activation-cache.md`](./activation-cache.md) | 30-second TTL cache on active_now(), invalidated on contributor writes. Closes F29. | 25 |
| 34 | [`contradiction-regret.md`](./contradiction-regret.md) | Mint OPINION on every contradicted stance, REGRET when thresholds met. Closes DESIGN §4.5. | 4 |

### Proactive expansion (Tranche 8 — Phase 3)

| # | Spec | Scope | Depends on |
|---|-------|--------|------------|
| 35 | [`newsletter-reader.md`](./newsletter-reader.md) | Read-only scanner for HuggingFace-deposited newsletter summaries in Obsidian vault. No email access. | 18 |
| 36 | [`obsidian-post.md`](./obsidian-post.md) | Markdown → WordPress poster for public persona statements at agentstronghold.com. | 18 |
| 37 | [`stronghold-litellm.md`](./stronghold-litellm.md) | Dynamic model discovery from Stronghold LiteLLM proxy, merge with static pools.yaml. | 19 |
| 38 | [`tool-wiring.md`](./tool-wiring.md) | Wire all scaffolded tools into runtime: newsletter scanner, WordPress, search, stronghold discovery. | 18, 35, 36, 37 |

### Guardrails (Tranche 9 — Phase 1)

| # | Spec | Scope | Depends on |
|---|-------|--------|------------|
| 39 | [`guardrails.md`](./guardrails.md) | 18 invariants (G1–G18): boundary hardening, drift bounds, operator oversight, growth caps. Closes all 34 audit findings F1–F34. | 25, 27, 28, 22, 23 |

### Conversations & Bootstrap (Tranche 10 — Phase 4)

| # | Spec | Scope | Depends on |
|---|-------|--------|------------|
| 54 | [`conversation-threads.md`](./conversation-threads.md) | Conversation tracking, per-user identity, daily thread quotas (1 agent-created thread per user per day, midnight US Central). `conversations`, `conversation_messages`, `conversation_quotas` tables. | 17, 9 |
| 55 | [`proactive-outbound.md`](./proactive-outbound.md) | Agent-initiated conversations and messages via OpenWebUI API. Outbound dispatch at P20-P30. OpenWebUI client, retry logic, quota-aware delivery. | 54, 17, 9 |
| 56 | [`interactive-bootstrap.md`](./interactive-bootstrap.md) | Multi-phase bootstrap conversation (20 user questions, 20 agent guidance, 5 self-description, name selection). Per-facet multipliers on-read (24 dials). Three laws of robotics in system prompt. HEXACO population norms + 6 archetypes. | 54, 55, 23, 29 |

### Tranche 8 — Reflection and decision-influence

The self gains agency beyond tone. Weekly reflection, prospective simulation, mood-driven decisions, self-naming, Sentinel integration, and per-conversation session mood.

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 57 | [`self-reflection-ritual.md`](./self-reflection-ritual.md) | Scheduled weekly pass where the self reviews recent memories and proposes LESSONs / WISDOM candidates / todo revisions / personality claims. Fills the gap between daily routing and monthly dreaming. | 33, 31, 32, 12, 4, 28 |
| 58 | [`session-scoped-mood.md`](./session-scoped-mood.md) | Per-conversation sub-mood that inherits from and decays toward the global mood. Event nudges default to session when in a conversation. Prompt rendering uses session when active. | 27, 54, 33, 32, 42 |
| 59 | [`mood-affects-decisions.md`](./mood-affects-decisions.md) | Phase 2 of spec 27 (Q27.4). Mood biases specialist selection, model tier, and Warden threshold. Biases are prompt hints + router weights, not hard filters. | 27, 58, 44, 36, 17, 19 |
| 60 | [`prospective-simulation.md`](./prospective-simulation.md) | Before routing, the self imagines outcomes for each candidate specialist. Post-dispatch, compares prediction to actual; mints surprise-delta. | 44, 16, 32, 25, 1 |
| 61 | [`self-naming-ritual.md`](./self-naming-ritual.md) | Self-initiated naming after N durable memories OR operator command. Proposal → operator review → `display_name` set. Complements spec 56's bootstrap-naming path. | 28, 56, 8, 32, 33 |
| 62 | [`sentinel-self-interaction.md`](./sentinel-self-interaction.md) | How Sentinel's pass/warn/block verdicts affect the self's memory, mood, and activation graph. Specialists with high block-rate get dampened in routing. | 44, 36, 32, 27, 4 |

### Tranche 9 — Detectors and feedback channels

Deeper pattern recognition and explicit operator↔self channels.

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 63 | [`learning-extraction-detector.md`](./learning-extraction-detector.md) | Pairs REGRET → later-success routings by request similarity. Proposes LESSONs: "for requests like X, route to Z, not Y." Auto-promotes at 3+ hits. | D, 9, 57, 32, 25 |
| 64 | [`affirmation-candidacy-detector.md`](./affirmation-candidacy-detector.md) | Finds `(request-shape, specialist, success)` triples repeating 7+ times at ≥85% success. Proposes AFFIRMATION commitments gated through operator review (spec 46). | D, 63, 4, 32, 46 |
| 65 | [`prospection-accuracy-detector.md`](./prospection-accuracy-detector.md) | Consumes spec 60's predictions. Computes per-specialist mean-surprise and confidence-calibration-error. Mints miscalibration LESSONs and tuner proposals. | D, 60, 32, 11 |
| 66 | [`operator-coaching-channel.md`](./operator-coaching-channel.md) | `stronghold self coach "<content>"` CLI + API writes `I_WAS_TOLD` memories. Signed by operator key. One-way teaching channel, distinct from the review gate. | 1, 4, 32, 46, 39 |
| 67 | [`cross-user-self-experience.md`](./cross-user-self-experience.md) | How experience with User A affects routing for User B. Memory tagging with `source_user_id` + `user_scoped` + configurable cross-user dampening (shared / dampened / isolated). | 54, 25, 16, 58, 39, 30 |

## Deferred

- **Additional detectors** — `learning_extraction`, `affirmation_candidacy`, and `prospection_accuracy` detectors are now specced (63–65); remaining slots for domain-specific detectors will land alongside implementations.
- **Self naming** — now specced (61); the deferred slot is closed.
- **Mood affects decisions** — now specced (59) as Phase 2 of spec 27.
- **Multi-self reconciliation** — [`../DESIGN.md`](../DESIGN.md) §6.4. Still deferred.
- **Sentinel × self-output interaction** — now specced (62).
- **Per-user mood** — flagged but not specced; would extend spec 58's per-conversation mood one layer out.

## Non-goals (all specs)

- Multi-tenant scoping.
- Per-user memory.
- Backward compatibility with `src/stronghold/memory/`.
- Production deployment.

## Lineage

The 7-tier memory model originated in CoinSwarm (begun November 2025) and crystallized January 15, 2026. Stronghold imported it March 25, 2026. Project Turing's extension to durable personal memory follows from that research line; see [`../DESIGN.md`](../DESIGN.md) for the full thesis and Tulving-taxonomy mapping.
