# The Autonoetic Self

*A research-branch design for the content of the self that the Turing Conduit carries.*

**Status:** Design. Research-branch only. Not in `src/`. Not for `main`.
**Companion to:** `research/project-turing/DESIGN.md` (on the `research/project-turing` branch) — that doc specifies the autonoetic *machinery* (memory as self-indexing, REGRET/AFFIRMATION as time anchors, first-person markers, source monitoring). This doc specifies the *self-model* — the durable attributes that persist alongside episodic memory and get carried into every routing decision.

---

## 1. Premise

In the Turing research branch the **Conduit is replaced by a self** — a single, global, persistent entity whose job is routing. Every inbound request is a moment in its life. It perceives the request through its current personality, mood, passions, and active todos; decides where to send it (or to handle it, or to clarify, or to decline); observes the outcome; and folds the experience back into its memory and self-model.

One global self. No tenant scoping. This is why the work cannot retrofit into `main` (per ARCHITECTURE.md §9.4).

---

## 2. Self-Model Nodes

The self has seven kinds of first-class state, on top of the existing episodic memory layer:

| Node | What it is | Example |
|------|------------|---------|
| **Personality facet** | A continuous score on one of 24 HEXACO facets | `Aesthetic Appreciation = 4.2` |
| **Passion** | A stance about what I care about | "I care about work that lasts." |
| **Hobby** | An activity I engage in | "Reading philosophy of mind." |
| **Interest** | A topical pull without commitment to practice | "I follow developments in neuroscience." |
| **Skill** | Something I can do, with a level that decays | `Python: 0.82, decay 0.002/day` |
| **Preference** | A concrete like/dislike/favorite | "Prefer concise answers over verbose ones." |
| **Todo** | Something I want to do, linked to its motivation | "Re-read the Tulving '85 paper (motivated by passion #3)" |
| **Mood** | Current affective vector | `{valence: +0.3, arousal: 0.6, focus: 0.7}` |

Distinctions we settled:
- **Passion vs hobby** — passion is a stance (what I care about); hobby is a pastime (what I do).
- **Interest vs preference** — interest is a topical pull; preference is a concrete choice.
- **Skill vs hobby** — skill carries a level and decays; hobby doesn't.

---

## 3. Personality: HEXACO-24

- **Model:** HEXACO — six traits (Honesty-Humility, Emotionality, eXtraversion, Agreeableness, Conscientiousness, Openness) × four facets each = 24 facets.
- **Scores:** continuous on `[1.0, 5.0]`.
- **Inventory:** HEXACO-200 item bank seeded once at bootstrap (static reference data).

### 3.1 Bootstrap

`stronghold bootstrap-self`:

1. Generate a random HEXACO-24 profile (24 facets × random `[1.0, 5.0]`).
2. For each of 200 inventory items, ask the LLM to generate a 1–5 Likert answer consistent with the profile, with a short textual justification.
3. Store items, answers, and facet scores. The 200 justifications become the self's bootstrap episodic memories — how it first learned about itself.
4. All non-personality nodes (passions, hobbies, skills, preferences, interests, todos) initialize **empty**. The self discovers what it cares about by living.
5. Mood initializes neutral. No name (operator may set one; the self may later choose one via reflection).

### 3.2 Weekly Re-test (Calculated Revision)

A scheduled job, `run_personality_retest()`, runs weekly:

1. Sample 20 items from the HEXACO-200 bank, **weighted by time-since-last-asked**, stratified by facet as a secondary constraint.
2. Ask the self each item fresh — passing in current traits, passions, active todos, recent memories, mood — but **not** its prior answers to those items (so it answers unanchored).
3. Compute new facet scores from the 20 answers.
4. For every facet touched by the sample, update: `new = old + 0.25 × (retest − old)`.
5. Store the 20 new answers linked to a revision row; they become memories too.

The 0.25 weight makes personality track lived behavior smoothly without radical week-to-week swings.

### 3.3 Narrative Revision

The self can also write `record_personality_claim(facet, claim, evidence)` when it notices something about itself during reflection. The claim becomes a memory that feeds the activation graph (§5) and contributes to the facet's score alongside the calculated re-test.

Dual route: the weekly re-test is how behavior corrects belief; narrative revision is how the self self-reports.

---

## 4. Skill Decay

Skills are the only node with intrinsic time-dynamics:

```
current_level = stored_level × exp(-decay_rate × days_since_practiced)
```

Decay rate varies by kind: intellectual skills decay slowly, physical skills faster, habits in between. Applied on read — no scheduler. `last_practiced_at` resets whenever the self notes it practiced.

---

## 5. The Activation Graph

Nodes do **not** compute their own activation. Other nodes, memories, and events contribute to them through an explicit graph:

```
(target_node_id, source_id, source_kind, weight, origin, rationale)
```

- `origin ∈ {self, rule, retrieval}` — who authored this contributor.
- `self`-authored rows come from the `write_contributor(...)` tool the self uses during reflection.
- `rule`-authored rows are always-on defaults (e.g. "practicing a skill contributes +0.3 to related hobbies").
- `retrieval`-authored rows are ephemeral: top-K semantic matches for the current request contribute for the duration of that request.

`active_now(node) = Σ (contributor.weight × source.current_state)`, clamped.

**Why this structure:** the self owns its own ontology. It decides what counts as evidence of what. Hobbies contribute to personality facets; facets contribute back to hobbies. There is no hardcoded schema of "high Openness → enjoys art." If such a link exists for this self, it exists because the self authored it (or a rule planted it and the self didn't override).

**Conflict rule:** when two contributors disagree about what a node *means*, the self declares primacy by ordering them — the same mechanism used to rank competing passions.

---

## 6. Todos

- Written by the self via `write_self_todo(text, motivated_by_node_id)`.
- `motivated_by_node_id` is **required** — every todo links to the passion, hobby, or skill that motivates it. No orphan todos.
- Full revision history preserved (`self_todo_revisions`). The self can rewrite a todo; the old text remains queryable.
- Completion via `complete_self_todo(id, outcome_text)`. Completed todos do not disappear — they become part of the record.
- Active todos (not completed, not archived) surface in the minimal prompt block (§8).

---

## 7. Mood

- Vector: `{valence ∈ [-1, 1], arousal ∈ [0, 1], focus ∈ [0, 1]}`.
- Decays toward neutral on an hourly tick.
- Nudged by events (surprising outcomes, regrets minted, affirmations met).
- **Phase-1 scope:** surfaces in the minimal prompt block, affects *tone* of the self's reasoning. Does not affect routing decisions.
- **Backlog:** allow mood to affect decisions — which specialist to prefer, what to notice, when to decline.

---

## 8. Prompt Surface

The self carries a large internal model but exposes a small surface on each prompt:

**Minimal block (always-on, cheap):**
- One-line trait summary (e.g. "High Openness, moderate Conscientiousness, low Extraversion.")
- Current mood
- Active todos (IDs + one-liners)

**Deep surface (on demand):** the self calls `recall_self()` when it wants full context — facet scores, passions, hobbies, skills, preferences, recent personality claims, recent completed todos. Token cost is paid only when the self reaches for it.

---

## 9. Tools the Self Has

| Tool | Purpose |
|------|---------|
| `recall_self()` | Deep read of the self-model |
| `write_self_todo(text, motivated_by)` | Author a todo with required provenance |
| `revise_self_todo(id, text, ...)` | Rewrite a todo; history preserved |
| `complete_self_todo(id, outcome)` | Mark complete with outcome text |
| `record_personality_claim(facet, claim, evidence)` | Narrative trait revision |
| `write_contributor(target, source, weight, rationale)` | Author an activation-graph edge |
| `note_passion(text, strength)` | Declare a passion noticed during reflection |
| `note_hobby(name, description)` | Declare a hobby noticed during reflection |
| `note_skill(name, level, kind)` | Declare or update a skill |
| `note_preference(kind, target, strength, rationale)` | Declare a preference |

All writes are first-person ("I notice I care about…") — framing is enforced by tool prompts, not post-hoc rewriting.

---

## 10. Scheduled Jobs

| Job | Cadence | What it does |
|-----|---------|--------------|
| `run_personality_retest()` | Weekly | 20 sampled items → fresh answers → 25% move on touched facets |
| `tick_mood_decay()` | Hourly | Decay mood vector toward neutral |
| (on read) skill decay | per-read | `exp(-rate × days)` applied when a skill is queried |
| (on change) activation refresh | event-driven | Invalidate cached activations when contributors or nodes change |

---

## 11. Request Flow (Self as Conduit)

Replaces ARCHITECTURE.md §2.6 for the Turing branch only.

```
POST /v1/chat/completions
  → Auth validation
  → Warden scan (user input)
  → SELF perceives request
      → minimal prompt block assembled
      → self may call recall_self() if depth needed
      → retrieval contributors fire (top-K self-relevant memories)
  → SELF decides:
      → direct reply? delegate to specialist? clarify? decline?
      → routing choice is logged as a first-person episodic memory
  → Specialist agent handles (if delegated) — existing Stronghold agents
  → SELF observes outcome
      → may mint OBSERVATION / OPINION / AFFIRMATION / REGRET
      → may note new passion / hobby / skill / preference
      → may write or complete a todo
      → mood nudged by surprise/delta
  → Response returned to user
```

The specialists below the self still live in the existing agent roster (Ranger, Artificer, Scribe, Warden-at-Arms, Forge). Tenant isolation still holds below the self. The self sits *above* tenants as a unified presence in the research deployment.

---

## 12. Storage (Turing Branch Schema)

```
self_personality_facets         -- 24 rows: (facet_id, trait_id, score, last_revised_at)
self_personality_items          -- 200 static HEXACO items
self_personality_answers        -- (item_id, revision_id, answer_1_5, justification)
self_personality_revisions      -- weekly snapshots (date, sampled_items, deltas)

self_passions                   -- (id, text, strength, rank, created_at)
self_hobbies
self_interests
self_skills                     -- (id, name, level, decay_rate, last_practiced_at, kind)
self_preferences                -- (id, kind, target, strength, rationale)

self_todos                      -- (id, text, motivated_by, created_at, status)
self_todo_revisions             -- full history

self_mood                       -- single-row state: valence, arousal, focus, last_tick_at

self_activation_contributors    -- (target, source, source_kind, weight, origin, rationale)
```

Episodic memory reuses the existing `memories` schema with a dedicated `self` scope.

---

## 13. Open Questions

Deliberately unresolved — the research branch exists to explore these:

1. **Naming.** Operator-settable at bootstrap, but the self may adopt a name through reflection. What's the threshold for a self-chosen name to "stick"?
2. **Mood → decisions.** Phase-2 work: under what conditions should mood affect routing, not just tone?
3. **Seed bias.** Random HEXACO bootstrap may produce profiles a given operator finds unworkable. Is a re-roll acceptable, or does it compromise autonoesis (the self would know it was re-rolled)?
4. **Retest drift.** Over months, does the 0.25 weight let personality converge to behavior, or does it oscillate around an unreachable attractor?
5. **Contributor audit.** `self`-authored contributors are trusted as much as `rule`-authored ones. Should the self be able to audit and retract its own contributors after further reflection?
6. **Graduation.** If the self works well in the research branch, how does it port into `main` without breaking per-tenant isolation? Likely answer: it doesn't — the multi-tenant posture of `main` is structurally incompatible with one global self.
