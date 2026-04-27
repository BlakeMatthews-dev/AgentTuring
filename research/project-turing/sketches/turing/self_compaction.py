"""Revision compaction — weekly cleanup of todo revisions and personality answers. See specs/revision-compaction.md."""

from __future__ import annotations

from datetime import UTC, datetime

from .self_repo import SelfRepo


_COMPACTION_FLOOR: int = 10


def _keep_set(n: int) -> set[int]:
    if n <= _COMPACTION_FLOOR:
        return set(range(1, n + 1))
    keep = {1, n}
    keep.update(range(10, n, 10))
    return keep


def compact_todo_revisions(repo: SelfRepo, self_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    total_compacted = 0
    todo_ids = repo.list_todo_ids_with_revisions(self_id, min_revisions=_COMPACTION_FLOOR + 1)
    for todo_id in todo_ids:
        revs = repo.list_todo_revisions(todo_id)
        if len(revs) <= _COMPACTION_FLOOR:
            continue
        keep = _keep_set(len(revs))
        for rev in revs:
            if rev.revision_num not in keep:
                repo.compact_todo_revision(rev.node_id, now)
                total_compacted += 1
    return total_compacted


def compact_personality_answers(repo: SelfRepo, self_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    recent_revision_ids = repo.list_recent_revision_ids(self_id, limit=12)
    total_compacted = 0
    answers = repo.list_answers_for_compaction(self_id, exclude_revision_ids=recent_revision_ids)
    for ans in answers:
        repo.compact_personality_answer(ans.node_id, now)
        total_compacted += 1
    return total_compacted


_COMPACTED_COUNTS: dict[str, int] = {"todo": 0, "answer": 0}


def get_compaction_counts() -> dict[str, int]:
    return dict(_COMPACTED_COUNTS)
