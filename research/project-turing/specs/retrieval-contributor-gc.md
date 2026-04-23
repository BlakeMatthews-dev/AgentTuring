# Spec 50 — Retrieval-contributor GC (G7)

*Scheduled and opportunistic deletion of expired `origin = retrieval` rows. Closes F13.*

**Depends on:** [activation-graph.md](./activation-graph.md), [runtime-reactor.md](./runtime-reactor.md), [self-schedules.md](./self-schedules.md).
**Depended on by:** —

---

## Current state

`active_contributors_for(..., at=now)` filters out expired retrieval rows but never deletes them. The table grows unbounded — at K=8 contributors × 100 requests/day = 800 dead rows/day per active deployment.

## Target

1. Scheduled sweep every `RETRIEVAL_GC_INTERVAL_TICKS = 1000` reactor ticks deletes every `origin = 'retrieval' AND expires_at < now()`.
2. Opportunistic GC: when `active_contributors_for` observes an expired-retrieval row AND the total non-expired row count for that target exceeds `GC_READ_THRESHOLD = 100`, delete the expired rows in-place.

## Acceptance criteria

### Scheduled sweep

- **AC-50.1.** At reactor startup, register a trigger `retrieval-gc:sweep` with `interval = RETRIEVAL_GC_INTERVAL_TICKS` ticks (≈ 1s at 1000Hz, so sub-second). Trigger handler calls `gc_expired_retrieval_contributors(repo)`. Test the trigger is registered.
- **AC-50.2.** `gc_expired_retrieval_contributors(repo)` runs:
  ```sql
  DELETE FROM self_activation_contributors
  WHERE origin = 'retrieval' AND expires_at < ?
  ```
  Returns deleted count. Test.
- **AC-50.3.** Sweep duration bounded by `GC_SWEEP_BUDGET_MS = 5`. If the DELETE exceeds the budget, the next sweep picks up from where it left off (no cursor needed because the query is idempotent). Test with a fixture that has 10k expired rows.

### Opportunistic GC

- **AC-50.4.** `active_contributors_for(target, now)` counts the rows it would return and deletes expired-retrieval rows in the same query when the count exceeds `GC_READ_THRESHOLD = 100`. Test via fabricated large-contributor target.
- **AC-50.5.** Opportunistic GC is scoped to the target's row set — does not touch other targets. Test.

### Metrics

- **AC-50.6.** Prometheus counter `turing_retrieval_gc_deleted_total{trigger="sweep"|"opportunistic"}` increments per delete. Test.
- **AC-50.7.** Gauge `turing_retrieval_contributors_live` reports current active retrieval row count (where `expires_at > now`). Test.

### Invariants

- **AC-50.8.** Post-sweep, no row exists with `origin = 'retrieval' AND expires_at < now()`. Property test over many fabricated expirations.
- **AC-50.9.** GC never deletes `origin IN ('self', 'rule')` rows. Test.
- **AC-50.10.** GC never deletes rows with `retracted_by` set (those are audit rows). Test.

### Edge cases

- **AC-50.11.** Rapid clock skew (system time jumps backward) produces rows where `expires_at > now` that were previously eligible. These are not deleted retroactively; they remain active. Test.
- **AC-50.12.** A row whose `expires_at = now` exactly: not deleted (strict `<`). Test.
- **AC-50.13.** GC is not transactional with writes — a contributor inserted mid-sweep is safe. SQLite handles this via the default isolation level. Test.

## Implementation

```python
# self_activation_gc.py (new module)

GC_SWEEP_BUDGET_MS: int = 5
GC_READ_THRESHOLD: int = 100
RETRIEVAL_GC_INTERVAL_TICKS: int = 1000


def gc_expired_retrieval_contributors(repo) -> int:
    cursor = repo.conn.execute(
        "DELETE FROM self_activation_contributors "
        "WHERE origin = 'retrieval' AND expires_at < ?",
        (datetime.now(UTC).isoformat(),),
    )
    repo.conn.commit()
    deleted = cursor.rowcount
    if deleted > 0:
        metrics.retrieval_gc_deleted_total.labels(trigger="sweep").inc(deleted)
    return deleted


def _active_contributors_for_with_gc(repo, target_node_id: str, at: datetime):
    now_iso = at.isoformat()
    rows = repo.conn.execute(
        """SELECT * FROM self_activation_contributors
             WHERE target_node_id = ?
               AND (expires_at IS NULL OR expires_at > ?)
               AND retracted_by IS NULL""",
        (target_node_id, now_iso),
    ).fetchall()

    if len(rows) > GC_READ_THRESHOLD:
        deleted = repo.conn.execute(
            """DELETE FROM self_activation_contributors
                 WHERE target_node_id = ?
                   AND origin = 'retrieval'
                   AND expires_at < ?""",
            (target_node_id, now_iso),
        ).rowcount
        if deleted > 0:
            metrics.retrieval_gc_deleted_total.labels(trigger="opportunistic").inc(deleted)
    return [row_to_contributor(r) for r in rows]
```

Register at reactor init:
```python
reactor.register_interval_trigger(
    name="retrieval-gc:sweep",
    interval_ticks=RETRIEVAL_GC_INTERVAL_TICKS,
    handler=lambda: gc_expired_retrieval_contributors(repo),
    idempotent=True,
)
```

## Open questions

- **Q50.1.** Sweep interval of 1000 ticks (1s). Alternative: time-based (`timedelta(seconds=10)`) for predictability. Tick-based is cheaper (no clock read).
- **Q50.2.** `GC_READ_THRESHOLD = 100` is arbitrary. The idea: only GC during reads where it's clearly needed, avoid write-hot contention. Tune after observing table growth patterns.
- **Q50.3.** Deleted rows are gone forever. An alternative is a "soft GC" that flags rows with `gc_archived_at` and a later hard-delete. Soft GC helps forensics of "what was active yesterday" but doubles storage. Not worth it for retrieval rows (ephemeral by design).
