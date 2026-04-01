"""Protocols for the RLHF feedback loop.

PRReviewer: reviews a PR and produces structured findings.
FeedbackExtractor: converts review findings into Learning objects.
ViolationStore: tracks violation metrics over time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.feedback import (
        ReviewFinding,
        ReviewResult,
        ViolationCategory,
        ViolationMetrics,
    )
    from stronghold.types.memory import Learning


@runtime_checkable
class FeedbackExtractor(Protocol):
    """Converts review findings into learnings for the authoring agent."""

    def extract_learnings(self, result: ReviewResult) -> list[Learning]:
        """Convert review findings into Learning objects scoped to the author agent."""
        ...


@runtime_checkable
class ViolationStore(Protocol):
    """Tracks violation metrics over time for trend analysis."""

    def record_finding(self, finding: ReviewFinding, *, agent_id: str) -> None:
        """Record a single violation finding."""
        ...

    def record_review(self, result: ReviewResult) -> None:
        """Record a complete review result (updates per-PR metrics)."""
        ...

    def get_metrics(self, agent_id: str) -> ViolationMetrics:
        """Get violation metrics for an agent."""
        ...

    def get_top_violations(
        self,
        agent_id: str,
        *,
        limit: int = 5,
    ) -> list[tuple[ViolationCategory, int]]:
        """Get most frequent violation categories for an agent."""
        ...
