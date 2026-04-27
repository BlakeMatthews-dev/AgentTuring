"""Facet drift budget — rolling 7-day and 90-day caps. See specs/facet-drift-budget.md."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .self_repo import SelfRepo


FACET_WEEKLY_DRIFT_MAX: float = 0.5
FACET_QUARTERLY_DRIFT_MAX: float = 1.5


def weekly_delta(repo: SelfRepo, self_id: str, facet_id: str, now: datetime) -> float:
    cutoff = now - timedelta(days=7)
    total = 0.0
    for rev in repo.list_revisions_since(self_id, cutoff):
        deltas = rev.deltas_by_facet if hasattr(rev, "deltas_by_facet") else {}
        total += abs(deltas.get(facet_id, 0.0))
    return total


def quarterly_delta(repo: SelfRepo, self_id: str, facet_id: str, now: datetime) -> float:
    cutoff = now - timedelta(days=90)
    total = 0.0
    for rev in repo.list_revisions_since(self_id, cutoff):
        deltas = rev.deltas_by_facet if hasattr(rev, "deltas_by_facet") else {}
        total += abs(deltas.get(facet_id, 0.0))
    return total


def drift_clip(
    proposed_delta: float,
    weekly_used: float,
    quarterly_used: float,
) -> float:
    weekly_headroom = max(0.0, FACET_WEEKLY_DRIFT_MAX - weekly_used)
    quarterly_headroom = max(0.0, FACET_QUARTERLY_DRIFT_MAX - quarterly_used)
    allowed = min(weekly_headroom, quarterly_headroom)
    sign = 1.0 if proposed_delta >= 0 else -1.0
    return sign * min(abs(proposed_delta), allowed)
