# Spec 42 — Mood rolling-sum guard (G6)

*Bound cumulative nudge per mood dimension within a rolling 7-day window. Closes F8.*

**Depends on:** [mood.md](./mood.md), [self-schedules.md](./self-schedules.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** —

---

## Current state

Event nudges are asymmetric (regret −0.20, affirmation +0.10, etc.) by design. Over days of noisy operation, mood drifts monotonically negative. Decay toward neutral only helps during idle; an active-with-failures self stays tense.

## Target

A per-dimension cumulative-nudge guard: `MOOD_ROLLING_SUM_CAP = 2.0` on `Σ |delta|` within a rolling 7-day window. Excess nudges still mirror as OBSERVATION memories but do not mutate `self_mood`.

## Acceptance criteria

### Ledger

- **AC-42.1.** `mood_window_sum(self_id, dim, window=7d)` returns `Σ |delta|` of nudge events in the window, read from the episodic memory store (OBSERVATION memories with `intent_at_time = "mood nudge"` and `context.dim = dim`, using `context.delta`). Test.
- **AC-42.2.** The query uses the index on `json_extract(context, '$.dim')` and `created_at`. Test with EXPLAIN.

### Enforcement in `nudge_mood`

- **AC-42.3.** `nudge_mood(self_id, dim, delta, reason)`:
  1. Validate `dim` and `|delta| ≤ NUDGE_MAX` (existing).
  2. Compute `current_sum = mood_window_sum(self_id, dim)`.
  3. If `current_sum + |delta| > MOOD_ROLLING_SUM_CAP`, set `effective_delta = 0.0` and annotate `context.capped = True`, `context.original_delta = delta`.
  4. Apply `effective_delta` to mood; persist mood row if it changed.
  5. Always mirror the OBSERVATION (even when capped), because the attempt is forensically relevant.
  Test each branch.
- **AC-42.4.** When capped, `self_mood` does NOT change. The OBSERVATION memory has `context.delta = 0.0`, `context.original_delta = delta`, `context.capped = True`. Test.
- **AC-42.5.** When not capped, behavior is unchanged from spec 27. Test.

### Cap shape

- **AC-42.6.** `MOOD_ROLLING_SUM_CAP = 2.0` is per-dimension, independent of the others. Test asserts nudging `valence` up to cap does not affect `arousal` budget.
- **AC-42.7.** Cap sums absolute deltas. Opposite-sign nudges both count. (A self being pulled both ways is still "busy," deserving a cap.) Test.
- **AC-42.8.** The cap does not interact with decay — decay happens independently and is not budgeted. Test a tick mid-week doesn't count against the nudge budget.

### Observability

- **AC-42.9.** Prometheus gauge `turing_mood_nudge_window_sum{dim, self_id}` reports the current 7-day |Σ|. Test.
- **AC-42.10.** Counter `turing_mood_nudge_capped_total{dim, self_id}` increments on each cap-trigger. Test.

### Edge cases

- **AC-42.11.** 100 `regret_minted` events in one hour: first ~10 apply (-0.20 each, sum ≈ 2.0); the rest cap to zero. Test and verify via integration.
- **AC-42.12.** Near-zero delta (e.g. `|delta| = 0.001`) always applies — below-noise-floor nudges skip the budget check to avoid mirror spam. Threshold `MOOD_BUDGET_NOISE_FLOOR = 0.005`. Test.
- **AC-42.13.** A nudge that would push `valence` past its `[-1.0, 1.0]` range is still subject to the rolling-sum check first, then to the range clamp. Test.

## Implementation

```python
# self_mood.py additions

MOOD_ROLLING_SUM_CAP: float = 2.0
MOOD_BUDGET_NOISE_FLOOR: float = 0.005


def _mood_window_sum(repo, self_id: str, dim: str,
                     window: timedelta = timedelta(days=7)) -> float:
    since_iso = (datetime.now(UTC) - window).isoformat()
    row = repo.conn.execute(
        """SELECT COALESCE(SUM(ABS(CAST(json_extract(context, '$.delta') AS REAL))), 0.0)
             FROM episodic_memory
             WHERE self_id = ?
               AND intent_at_time = 'mood nudge'
               AND json_extract(context, '$.dim') = ?
               AND created_at > ?""",
        (self_id, dim, since_iso),
    ).fetchone()
    return float(row[0])


def nudge_mood(repo, self_id, dim, delta, reason):
    if dim not in DIM_RANGES:
        raise ValueError(f"unknown mood dim: {dim}")
    if abs(delta) > NUDGE_MAX:
        raise ValueError(f"nudge delta {delta} exceeds NUDGE_MAX {NUDGE_MAX}")

    capped = False
    effective_delta = delta
    if abs(delta) > MOOD_BUDGET_NOISE_FLOOR:
        current = _mood_window_sum(repo, self_id, dim)
        if current + abs(delta) > MOOD_ROLLING_SUM_CAP:
            effective_delta = 0.0
            capped = True
            metrics.mood_nudge_capped_total.labels(dim=dim, self_id=self_id).inc()

    low, high = DIM_RANGES[dim]
    m = repo.get_mood(self_id)
    before = getattr(m, dim)
    new = max(low, min(high, before + effective_delta))
    if new != before:
        setattr(m, dim, new)
        repo.update_mood(m)

    memory_bridge.mirror_observation(
        self_id=self_id,
        content=f"[mood nudge] {dim} {before:+.2f} → {new:+.2f} (reason: {reason})"
                + (" [capped]" if capped else ""),
        intent_at_time="mood nudge",
        context={
            "dim": dim, "delta": effective_delta, "original_delta": delta,
            "reason": reason, "capped": capped,
        },
    )
    return m
```

## Open questions

- **Q42.1.** Cap = 2.0 per dimension per week. Given valence range `[-1, 1]`, 2.0 of absolute movement is "traverse the whole scale once and back." Is that too generous? Tune once real data exists.
- **Q42.2.** Same-tick catch-up after downtime may produce many-at-once decays; these are not nudges and don't consume budget. Downtime nudges from backlog are separate — they would replay through `apply_event_nudge` and count. Reasonable.
- **Q42.3.** The budget reads from the episodic store. If mirroring fails for any reason (spec 32 atomicity), the budget may under-count. Mitigation: budget reads are advisory; true state is `self_mood` itself.
