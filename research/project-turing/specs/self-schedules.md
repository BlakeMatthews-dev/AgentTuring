# Spec 33 — Self-schedules: registering mood decay and weekly retest with the Reactor

*`tick_mood_decay` and `run_personality_retest` exist as library functions but are never registered with the Reactor. Closes F37.*

**Depends on:** [runtime-reactor.md](./runtime-reactor.md), [mood.md](./mood.md), [personality.md](./personality.md), [self-bootstrap.md](./self-bootstrap.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** [mood-rolling-sum-guard.md](./mood-rolling-sum-guard.md), [facet-drift-budget.md](./facet-drift-budget.md).

---

## Current state

- `self_mood.tick_mood_decay(self_id, now)` exists; nothing calls it on a schedule.
- `self_personality.apply_retest(...)` exists; no wrapper binds it to a weekly cadence or plumbs the LLM ask-callable.
- `self_bootstrap.finalize(...)` creates the mood row but does not register any reactor triggers, contrary to spec 29 AC-29.16.

## Target

Two Reactor triggers per bootstrapped self, registered at `finalize()` time:
1. Hourly interval trigger calling `tick_mood_decay(self_id)`.
2. Weekly interval trigger (first fire at `finalize_at + 7d`) calling `run_personality_retest(self_id)`, which wraps sampling + LLM plumbing + `apply_retest`.

Both triggers survive process restart via reactor persistence (spec 20). Both are named so re-registration is idempotent after a crash mid-bootstrap.

## Acceptance criteria

### Registration

- **AC-33.1.** `finalize(repo, self_id)` registers `trigger_name = f"mood-decay:{self_id}"` as an interval trigger with `interval = MOOD_DECAY_INTERVAL = timedelta(hours=1)`, `handler = lambda: tick_mood_decay(repo, self_id, datetime.now(UTC))`. Test asserts the trigger is present on the Reactor after finalize.
- **AC-33.2.** `finalize` registers `trigger_name = f"personality-retest:{self_id}"` as an interval trigger with `interval = timedelta(days=7)`, `first_fire_at = finalize_at + timedelta(days=7)`. Test.
- **AC-33.3.** Re-registering the same named trigger is idempotent — the Reactor returns the existing trigger unchanged rather than duplicating. Test asserts no double-registration after a simulated re-`finalize`.

### `run_personality_retest` wrapper

- **AC-33.4.** `run_personality_retest(self_id, *, ask_self=None)` loads the item bank, computes `last_asked`, invokes `sample_retest_items` with a seeded `random.Random`, then calls `apply_retest`. The `ask_self` callable is either supplied (tests) or constructed by the runtime as an LLM call against the configured pool.
- **AC-33.5.** A retest failure (LLM invalid output, DB error) writes a LESSON memory `"retest attempt failed: {reason}"` and does not mutate facet scores. The next scheduled fire proceeds normally. Test with a failing fake ask.
- **AC-33.6.** Each retest completion writes a LESSON memory via `mirror_lesson(intent_at_time="personality retest complete", context={"revision_id", "deltas_by_facet"})`. Test.

### Mood tick behavior

- **AC-33.7.** Each hourly tick calls `tick_mood_decay` exactly once per `self_id`. Test with FakeReactor advanced 24 simulated hours produces 24 calls.
- **AC-33.8.** Downtime catch-up: a reactor resumed after 100 hours produces exactly one `tick_mood_decay` call (spec 27 AC-27.5 — compound decay handles the elapsed time; duplicate calls would over-correct). Test.

### Unregistration

- **AC-33.9.** Archiving a self (setting `self_identity.archived_at`) unregisters both triggers. Test.

### Observability

- **AC-33.10.** `stronghold self triggers` (new inspect subcommand) lists every registered `self:*` trigger with its next fire time. Test.

## Implementation

```python
# self_bootstrap.py changes in finalize()

def finalize(repo: SelfRepo, self_id: str, reactor: Reactor) -> None:
    now = datetime.now(UTC)
    repo.insert_mood(Mood(self_id=self_id, valence=0.0, arousal=0.3,
                          focus=0.5, last_tick_at=now))
    reactor.register_interval_trigger(
        name=f"mood-decay:{self_id}",
        interval=timedelta(hours=1),
        handler=lambda: tick_mood_decay(repo, self_id, datetime.now(UTC)),
        idempotent=True,
    )
    reactor.register_interval_trigger(
        name=f"personality-retest:{self_id}",
        interval=timedelta(days=7),
        first_fire_at=now + timedelta(days=7),
        handler=lambda: run_personality_retest(repo, self_id),
        idempotent=True,
    )
    memory_bridge.mirror_lesson(
        self_id=self_id,
        content=f"I was bootstrapped on {now.date().isoformat()}.",
        intent_at_time="self bootstrap complete",
    )
    repo.delete_bootstrap_progress(self_id)
```

`run_personality_retest` lives in `self_personality.py`:

```python
def run_personality_retest(
    repo: SelfRepo, self_id: str, *, ask_self: AskSelfCallable | None = None,
    now: datetime | None = None,
) -> PersonalityRevision | None:
    now = now or datetime.now(UTC)
    ask = ask_self or default_llm_ask(self_id)
    items = repo.list_items(self_id)
    last_asked = repo.last_asked_map(self_id)
    rng = random.Random(hash((self_id, now.isoformat())))
    sampled = sample_retest_items(items, last_asked, rng, now=now)
    try:
        return apply_retest(repo, self_id, sampled, ask_self=ask, now=now,
                            new_id=new_id)
    except Exception as e:
        memory_bridge.mirror_lesson(
            self_id=self_id,
            content=f"retest attempt failed: {e!r}",
            intent_at_time="personality retest failed",
        )
        return None
```

## Open questions

- **Q33.1.** Retest RNG seed uses `hash((self_id, now.isoformat()))` — deterministic per (self, week) for reproducibility. Alternative: pure random. Deterministic wins for auditability.
- **Q33.2.** Downtime catch-up calls `tick_mood_decay` once; its internal math does the compound decay. Should downtime catch-up ALSO fire one retest if a week was missed, or skip until the next aligned Monday? Current spec: fire one, because the retest is "update to reflect a week of living" and skipping loses a week.
- **Q33.3.** `stronghold self triggers` leaks per-self info across tenants in a multi-self deployment. Out of scope here (research is single-self) but flagged for any future multi-self port.
