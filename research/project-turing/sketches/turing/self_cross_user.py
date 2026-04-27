"""Cross-user self-experience — policy for multi-user influence. See specs/cross-user-self-experience.md."""

from __future__ import annotations

from enum import StrEnum


class CrossUserPolicy(StrEnum):
    SHARED = "shared"
    DAMPENED = "dampened"
    ISOLATED = "isolated"


_DAMPENING_FACTORS: dict[str, float] = {
    CrossUserPolicy.SHARED: 1.0,
    CrossUserPolicy.DAMPENED: 0.6,
    CrossUserPolicy.ISOLATED: 0.0,
}


def cross_user_dampening(policy: str) -> float:
    return _DAMPENING_FACTORS.get(policy, 0.6)


def effective_memory_weight(
    base_weight: float,
    source_user_id: str | None,
    requesting_user_id: str | None,
    policy: str,
    user_scoped: bool = False,
) -> float:
    if user_scoped and source_user_id != requesting_user_id:
        return 0.0
    if source_user_id is None or requesting_user_id is None:
        return base_weight
    if source_user_id == requesting_user_id:
        return base_weight
    factor = cross_user_dampening(policy)
    return base_weight * factor


def should_require_cross_user(detector_hits: int) -> bool:
    return detector_hits >= 2


ANONYMOUS_USER: str = "anonymous"
DEFAULT_POLICY: str = CrossUserPolicy.DAMPENED
