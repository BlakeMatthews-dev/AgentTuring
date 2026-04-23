# Spec 57 — Self-reflection ritual

*A scheduled weekly pass where the self reviews its own recent memories, promotes consistent patterns to LESSONs / WISDOM candidates, and optionally revises todos and notes. Fills the gap between daily routing and monthly dreaming.*

**Depends on:** [self-schedules.md](./self-schedules.md), [self-tool-registry.md](./self-tool-registry.md), [memory-mirroring.md](./memory-mirroring.md), [dreaming.md](./dreaming.md), [write-paths.md](./write-paths.md), [self-surface.md](./self-surface.md).
**Depended on by:** —

---

## Current state

The self has three rhythms:
- **Per-request:** perception → decision → observation (spec 30, 44).
- **Hourly:** mood decay tick (spec 27, 33).
- **Weekly:** personality retest (spec 23, 33).
- **Scheduled consolidation (spec 12 dreaming):** WISDOM candidacy runs but is pattern-driven across all memory, not self-curated.

What's missing is an explicit "I review what I did last week" pass — self-curated reflection that can produce LESSONs, propose WISDOM candidates to dreaming, revise active todos, and notice its own state.

## Target

A scheduled weekly ritual `run_self_reflection(self_id)`:
1. Read REGRETs, AFFIRMATIONs, completed todos, and highest-weight OBSERVATIONs from the last 7 days.
2. Call the reflection LLM with those memories + current self-model state (via `recall_self`).
3. LLM returns a structured reflection: zero or more LESSON candidates, zero or more WISDOM candidates (handed off to dreaming), optional todo revisions/completions, optional personality claims.
4. Every output passes standard gates (Warden per spec 36, budgets per spec 37, drift-clipping per spec 40, etc.).
5. Mirror the reflection session itself as a LESSON memory summarizing what was noticed.

Cadence: weekly. Default: Wednesdays 18:00 UTC (mid-week, offset from Sunday retest so reflection and retest don't contend).

## Acceptance criteria

### Scheduling

- **AC-57.1.** `finalize()` in bootstrap registers `self-reflection:{self_id}` as an interval trigger with `interval = timedelta(days=7)`, `first_fire_at = finalize_at + timedelta(days=(3 - weekday) % 7)` targeting Wednesday. Test via FakeReactor.
- **AC-57.2.** Trigger handler wraps `run_self_reflection(self_id)` with `request_scope(reflection_request_id)` (spec 39). Test.
- **AC-57.3.** Re-registration is idempotent by trigger name (spec 33 pattern). Test.

### Memory selection

- **AC-57.4.** `select_reflection_memories(self_id, now)` returns:
  - All REGRET memories from the last 7 days.
  - All AFFIRMATION memories from the last 7 days.
  - Top-N (default `REFLECTION_OBSERVATION_TOP_N = 20`) OBSERVATION memories from the last 7 days, ranked by weight × recency.
  - Completed todos from the last 7 days.
  - Currently-active todos.
  Capped at `REFLECTION_MEMORY_LIMIT = 50` rows total. Test.
- **AC-57.5.** If fewer than 3 memories are selected (low activity), the ritual logs OBSERVATION `"quiet week; nothing to reflect on"` and exits without LLM call. Test.

### Reflection LLM call

- **AC-57.6.** System prompt opens first-person: `"I am {self_id}. It is Wednesday. I am sitting down to reflect on the last week."` Contains `recall_self()` output and the selected memories. Token budget `REFLECTION_INPUT_BUDGET = 8000`; output budget `REFLECTION_OUTPUT_BUDGET = 3000`. Timeout `REFLECTION_TIMEOUT_SEC = 60`. Test.
- **AC-57.7.** The LLM is bound to a restricted tool set:
  - `propose_lesson(content, weight, evidence_memory_ids)` — writes a LESSON memory.
  - `propose_wisdom_candidate(content, rationale)` — adds to dreaming queue (spec 12).
  - `complete_self_todo(todo_id, outcome_text)` (existing).
  - `revise_self_todo(todo_id, new_text, reason)` (existing).
  - `record_personality_claim(facet_id, claim, evidence)` (existing).
  - `note_passion`, `note_hobby`, `note_preference` (existing).
  `write_self_todo` is NOT in the reflection tool set — reflection reviews existing todos, doesn't author new ones. Test registry.

### Output constraints

- **AC-57.8.** Per-reflection output budget sums to at most:
  - 3 LESSON candidates.
  - 2 WISDOM candidates.
  - 5 todo revisions/completions.
  - 3 personality claims.
  Over-limit tool calls raise `ReflectionOutputBudgetExceeded`. Test.
- **AC-57.9.** All reflection writes are subject to Tranche 7 guardrails (Warden, drift budget, rate limits). A reflection that produces a Warden-blocked claim simply loses that claim; other outputs proceed. Test.

### Mirror memory

- **AC-57.10.** The reflection session itself mirrors as a LESSON memory: `content = f"I reflected on {date_range}. I proposed {N_lessons} lessons, {N_wisdom} wisdom candidates, revised {N_todos} todos."`, `intent_at_time = "self reflection complete"`, `context = {reflection_id, lesson_ids, wisdom_candidate_ids, ...}`. Test.

### Dreaming integration

- **AC-57.11.** `propose_wisdom_candidate(...)` inserts into a new `wisdom_candidates_pending` table (columns: `id, self_id, content, rationale, proposed_at, source = "reflection", consumed_by_dream_id`). The next dreaming session (spec 12) consumes pending candidates, applies its standard promotion criteria, and marks them consumed. Test.
- **AC-57.12.** Candidates older than `CANDIDATE_MAX_AGE = 30 days` are purged on dreaming's next run with an OBSERVATION memory `"reflection candidate expired unconsumed"`. Test.

### Failure modes

- **AC-57.13.** LLM timeout → OPINION memory `"reflection timed out; no changes committed"`, no mutations. Test.
- **AC-57.14.** Two overlapping reflections on the same self (shouldn't happen, but test) — second is rejected via an advisory lock `self-reflection:{self_id}`. Test.
- **AC-57.15.** Reflection during bootstrap incomplete → skipped with LESSON. Test.

### Observability

- **AC-57.16.** Histogram `turing_reflection_duration_seconds{self_id}`. Counter `turing_reflection_outputs_total{kind, self_id}` by output kind. Test.
- **AC-57.17.** `stronghold self inspect reflection [--since DATE]` lists reflection sessions with output summaries. Test.

### Edge cases

- **AC-57.18.** First reflection runs 7 days after bootstrap, even if the self has accumulated no memories of interest. Test.
- **AC-57.19.** A reflection that proposes a personality claim on a facet already at its weekly drift cap simply clips the contribution (spec 40), logs an OPINION memory citing the clip, and moves on. No exception. Test.
- **AC-57.20.** Reflection respects `CONDUIT_MODE` — runs regardless of mode (self/stateless). Stateless mode still lets the self reflect because reflection is not a routing operation. Test.

## Implementation

```python
# self_reflection.py

REFLECTION_INPUT_BUDGET: int = 8000
REFLECTION_OUTPUT_BUDGET: int = 3000
REFLECTION_TIMEOUT_SEC: int = 60
REFLECTION_OBSERVATION_TOP_N: int = 20
REFLECTION_MEMORY_LIMIT: int = 50
CANDIDATE_MAX_AGE: timedelta = timedelta(days=30)


async def run_self_reflection(
    repo: SelfRepo, self_id: str, *, now: datetime | None = None,
) -> ReflectionResult:
    now = now or datetime.now(UTC)
    with repo.advisory_lock(f"self-reflection:{self_id}"):
        if not _bootstrap_complete(repo, self_id):
            memory_bridge.mirror_lesson(
                self_id=self_id,
                content="reflection skipped; self not bootstrapped",
                intent_at_time="self reflection skipped",
            )
            return ReflectionResult.empty()

        memories = select_reflection_memories(repo, self_id, now)
        if len(memories) < 3:
            memory_bridge.mirror_observation(
                self_id=self_id,
                content="quiet week; nothing to reflect on",
                intent_at_time="self reflection skipped",
            )
            return ReflectionResult.empty()

        result = await _llm_reflect(repo, self_id, memories)
        memory_bridge.mirror_lesson(
            self_id=self_id,
            content=_summarize_reflection(result),
            intent_at_time="self reflection complete",
            context={"reflection_id": result.id, **result.output_ids()},
        )
        return result
```

Schema:
```sql
CREATE TABLE IF NOT EXISTS wisdom_candidates_pending (
    id                 TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL REFERENCES self_identity(self_id),
    content            TEXT NOT NULL,
    rationale          TEXT NOT NULL,
    proposed_at        TEXT NOT NULL,
    source             TEXT NOT NULL,   -- "reflection" | future sources
    consumed_by_dream_id TEXT,
    expired_at         TEXT
);
```

## Open questions

- **Q57.1.** Wednesdays at 18:00 UTC is a default; operator may want to align with their time zone. `REFLECTION_WEEKDAY_UTC` and `REFLECTION_HOUR_UTC` in `turing.yaml`.
- **Q57.2.** Output budgets (3/2/5/3) match the "small week of output" intuition. Tune empirically.
- **Q57.3.** Reflection doesn't allow `write_self_todo` because a "reflect, then plan" split feels cleaner than "reflect and plan in one sitting." Revisit if the self wants to author new todos during reflection.
- **Q57.4.** Reflection could also run after a REGRET-minting routing decision (event-driven reflection). Deferred; would be a separate trigger.
