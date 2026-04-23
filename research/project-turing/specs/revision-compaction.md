# Spec 53 — Revision and answer compaction (G11)

*Weekly compaction reduces `self_todo_revisions` and `self_personality_answers` storage without losing the narrative. Closes F14.*

**Depends on:** [self-todos.md](./self-todos.md), [personality.md](./personality.md), [runtime-reactor.md](./runtime-reactor.md).
**Depended on by:** —

---

## Current state

`self_todo_revisions` is append-only; a daily-revised todo accumulates 365 rows/year. `self_personality_answers` grows at 20/week plus 200 bootstrap = ~1040 rows/year/self. Both are unbounded.

## Target

Weekly compaction:
- **Todo revisions:** keep first, last, and every 10th; blank text columns on the rest with a `compacted_at` marker.
- **Personality answers:** keep all bootstrap answers (`revision_id IS NULL`) + answers tied to the 12 most recent retest revisions; compact older retest revisions to one aggregate row each.

## Acceptance criteria

### Todo-revision compaction

- **AC-53.1.** `compact_todo_revisions(repo, self_id)` — for each todo with > `REVISION_KEEP_FLOOR = 10` revisions, keep the first (revision_num = 1), the last (max revision_num), and every 10th in between (10, 20, ..., max-1). Blank `text_before` and `text_after` on compacted rows; set `compacted_at = now`. Test: a todo with 100 revisions retains exactly 12 text-full rows (1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 99, 100).
- **AC-53.2.** Blanked rows remain queryable — `list_todo_revisions` returns them with `text_before = text_after = "[compacted]"` when `compacted_at IS NOT NULL`. Test.
- **AC-53.3.** Compaction is idempotent: running twice on the same todo produces no change on the second run. Test.
- **AC-53.4.** Compaction cannot bypass the append-only trigger on `self_todo_revisions` because it does an UPDATE, not a DELETE; the trigger (spec 22) forbids both UPDATE and DELETE. Migration: relax the trigger to allow UPDATE where `compacted_at` was NULL and is being set, and only on text columns. Test.

### Answer compaction

- **AC-53.5.** `compact_personality_answers(repo, self_id)` — retain all answers with `revision_id IS NULL` (bootstrap) and answers tied to the `N_REVISION_KEEPS = 12` most recent retest revisions. For older retest revisions, keep one aggregate row per revision with `answer_1_5 = NULL`, `justification_text = "[compacted: N answers]"`, `asked_at = ran_at`. Test with fabricated 20 retest weeks.
- **AC-53.6.** Compaction preserves facet-score audit: older revisions' `deltas_by_facet` in `self_personality_revisions` is still queryable — per-facet history is reconstructable from that table even when per-item answers are compacted. Test.

### Scheduled execution

- **AC-53.7.** Register a reactor trigger `compaction:weekly` with `interval = timedelta(days=7)`, handler calls both compaction functions for the live self. Test the trigger is registered.
- **AC-53.8.** First run is at `deployment_start + 7d`; subsequent runs align to a fixed UTC weekday (Sundays) to give operators a predictable cadence. Test.

### Inspect surface

- **AC-53.9.** `stronghold self inspect compaction` reports:
  - Todos with > REVISION_KEEP_FLOOR revisions: count, last compaction time.
  - Answers table: total rows, compactable rows, time since last compaction.
  Test.

### Observability

- **AC-53.10.** Counter `turing_revisions_compacted_total{kind="todo"|"answer"}` increments per compaction run. Test.
- **AC-53.11.** Histogram `turing_compaction_duration_seconds{kind}`. Test.

### Edge cases

- **AC-53.12.** A todo with exactly 10 revisions is below the floor and not compacted. Test.
- **AC-53.13.** A todo revised twice since last compaction (first and last already kept) produces no-op. Test.
- **AC-53.14.** Concurrent compaction and a new revision: the new revision gets `revision_num = max + 1` and is kept (it's now the new "last"). The compaction run may have already written a "last" — it runs again next week. Test.
- **AC-53.15.** A compacted todo's full revision history can be reconstructed up to the level of detail retained. A UI note makes this honest: "older revisions compacted; full history available in archive."

## Implementation

```python
# self_compaction.py (new module)

REVISION_KEEP_FLOOR: int = 10
N_REVISION_KEEPS: int = 12


def compact_todo_revisions(repo, self_id: str) -> int:
    todos = repo.conn.execute(
        "SELECT DISTINCT todo_id FROM self_todo_revisions WHERE self_id = ?",
        (self_id,),
    ).fetchall()
    compacted = 0
    for (todo_id,) in todos:
        revs = repo.list_todo_revisions(todo_id)
        if len(revs) <= REVISION_KEEP_FLOOR:
            continue
        keep_nums = _keep_set(len(revs))  # {1, 10, 20, ..., last}
        for r in revs:
            if r.revision_num not in keep_nums and r.text_after != "[compacted]":
                repo.conn.execute(
                    """UPDATE self_todo_revisions
                          SET text_before = '[compacted]',
                              text_after = '[compacted]',
                              compacted_at = ?
                          WHERE node_id = ?""",
                    (datetime.now(UTC).isoformat(), r.node_id),
                )
                compacted += 1
    repo.conn.commit()
    return compacted


def _keep_set(n: int) -> set[int]:
    # Always keep 1 and n. Plus every 10th: 10, 20, ..., n-1.
    keep = {1, n}
    keep.update(range(10, n, 10))
    return keep


def compact_personality_answers(repo, self_id: str) -> int:
    recent_revs = repo.conn.execute(
        """SELECT revision_id FROM self_personality_revisions
           WHERE self_id = ? ORDER BY ran_at DESC LIMIT ?""",
        (self_id, N_REVISION_KEEPS),
    ).fetchall()
    keep_rev_ids = {r[0] for r in recent_revs}

    stale_answers = repo.conn.execute(
        """SELECT revision_id, COUNT(*) FROM self_personality_answers
           WHERE self_id = ? AND revision_id IS NOT NULL
           GROUP BY revision_id""",
        (self_id,),
    ).fetchall()

    compacted = 0
    for rev_id, count in stale_answers:
        if rev_id in keep_rev_ids:
            continue
        # Replace all answer rows for this rev with one aggregate row.
        ...
        compacted += count
    repo.conn.commit()
    return compacted
```

Schema migration to relax the append-only trigger on `self_todo_revisions`:

```sql
DROP TRIGGER self_todo_revisions_no_update;
CREATE TRIGGER self_todo_revisions_restrict_update
    BEFORE UPDATE ON self_todo_revisions
    WHEN OLD.compacted_at IS NOT NULL
       OR NEW.text_before IS OLD.text_after   -- prevents swapping original content
BEGIN
    SELECT RAISE(ABORT, 'self_todo_revisions update restricted to compaction');
END;
```

## Open questions

- **Q53.1.** Compaction drops text but preserves the revision count and timestamp. An operator curious about "what did my todo say on week 4" gets a "[compacted]" marker. Acceptable for revisions; not for bootstrap answers (preserved in full).
- **Q53.2.** Aggregate-row compaction for old retest answers loses per-item grain. An alternative is a separate `self_personality_answers_archive` table keyed by `revision_id` with a blob. Heavier; deferred.
- **Q53.3.** Sunday UTC cadence assumes operator attention aligned with a week boundary. Some deployments may prefer rolling (last run + 7d exactly). Config if needed.
- **Q53.4.** Trigger relaxation is narrow (only `compacted_at IS NULL` → value permitted). But any future migration needs to know this. Documented above the trigger definition.
