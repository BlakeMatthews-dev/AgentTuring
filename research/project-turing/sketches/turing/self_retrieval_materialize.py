"""Retrieval contributor materialization with count and weight caps. See specs/retrieval-contributor-cap.md."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .self_model import ActivationContributor, ContributorOrigin, NodeKind
from .self_repo import SelfRepo


K_RETRIEVAL_CONTRIBUTORS: int = 8
RETRIEVAL_SUM_CAP: float = 1.0
RETRIEVAL_WEIGHT_COEFFICIENT: float = 0.4
RETRIEVAL_TTL: timedelta = timedelta(minutes=5)

_DROP_COUNTS: dict[str, int] = {"count_cap": 0, "sum_cap": 0}


def get_drop_counts() -> dict[str, int]:
    return dict(_DROP_COUNTS)


def materialize_retrieval_contributors(
    repo: SelfRepo,
    self_id: str,
    now: datetime,
    per_target: dict[str, dict[str, float]],
    new_id,
) -> dict[str, int]:
    expires = now + RETRIEVAL_TTL
    inserted: dict[str, int] = {}

    for target_id, hits in per_target.items():
        sorted_hits = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
        running_sum = 0.0
        count = 0

        for source_id, sim in sorted_hits:
            if count >= K_RETRIEVAL_CONTRIBUTORS:
                _DROP_COUNTS["count_cap"] = _DROP_COUNTS.get("count_cap", 0) + 1
                break

            sim_clamped = min(1.0, max(0.0, sim))
            weight = sim_clamped * RETRIEVAL_WEIGHT_COEFFICIENT

            if running_sum + weight > RETRIEVAL_SUM_CAP:
                if count == 0:
                    weight = RETRIEVAL_SUM_CAP
                else:
                    _DROP_COUNTS["sum_cap"] = _DROP_COUNTS.get("sum_cap", 0) + 1
                    break

            repo.insert_contributor(
                ActivationContributor(
                    node_id=new_id("contrib"),
                    self_id=self_id,
                    target_node_id=target_id,
                    target_kind=NodeKind.PERSONALITY_FACET,
                    source_id=source_id,
                    source_kind="retrieval",
                    weight=weight,
                    origin=ContributorOrigin.RETRIEVAL,
                    rationale="retrieval",
                    expires_at=expires,
                ),
                acting_self_id=self_id,
            )
            running_sum += weight
            count += 1

        inserted[target_id] = count

    return inserted
