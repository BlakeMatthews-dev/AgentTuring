"""Activation contributor GC — sweep expired retrieval rows. See specs/retrieval-contributor-gc.md."""

from __future__ import annotations

from datetime import UTC, datetime

from .self_repo import SelfRepo


_GC_DELETED: dict[str, int] = {"sweep": 0, "opportunistic": 0}
GC_READ_THRESHOLD: int = 100


def gc_expired_retrieval_contributors(repo: SelfRepo, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    deleted = repo.delete_expired_retrieval_contributors(now)
    _GC_DELETED["sweep"] += deleted
    return deleted


def gc_opportunistic(repo: SelfRepo, target_node_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    count = repo.count_active_retrieval_contributors(target_node_id, now)
    if count <= GC_READ_THRESHOLD:
        return 0
    deleted = repo.delete_expired_retrieval_contributors_for_target(target_node_id, now)
    _GC_DELETED["opportunistic"] += deleted
    return deleted


def get_gc_counts() -> dict[str, int]:
    return dict(_GC_DELETED)
