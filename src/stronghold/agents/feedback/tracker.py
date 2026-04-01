"""InMemoryViolationTracker — tracks violation metrics over time.

Implements the ViolationStore protocol. Provides trend analysis to
measure whether the RLHF loop is working (are violations decreasing?).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from stronghold.types.feedback import ViolationCategory, ViolationMetrics

if TYPE_CHECKING:
    from stronghold.types.feedback import ReviewFinding, ReviewResult


class InMemoryViolationTracker:
    """Tracks violation counts and computes improvement trends.

    Implements the ViolationStore protocol.
    """

    def __init__(self) -> None:
        self._counters: dict[str, Counter[ViolationCategory]] = {}
        self._metrics: dict[str, ViolationMetrics] = {}

    def record_finding(self, finding: ReviewFinding, *, agent_id: str) -> None:
        """Record a single violation finding for an agent."""
        if agent_id not in self._counters:
            self._counters[agent_id] = Counter()
        self._counters[agent_id][finding.category] += 1

        metrics = self._get_or_create_metrics(agent_id)
        metrics.total_findings += 1
        metrics.category_counts[finding.category] = (
            metrics.category_counts.get(finding.category, 0) + 1
        )

    def record_review(self, result: ReviewResult) -> None:
        """Record a complete review, updating per-PR metrics."""
        agent_id = result.agent_id
        metrics = self._get_or_create_metrics(agent_id)
        metrics.total_prs_reviewed += 1

        for finding in result.findings:
            self.record_finding(finding, agent_id=agent_id)

        # Track findings-per-PR history for trend analysis
        findings_this_pr = len(result.findings)
        metrics.findings_per_pr_history.append(float(findings_this_pr))

    def get_metrics(self, agent_id: str) -> ViolationMetrics:
        """Get violation metrics for an agent."""
        return self._get_or_create_metrics(agent_id)

    def get_top_violations(
        self,
        agent_id: str,
        *,
        limit: int = 5,
    ) -> list[tuple[ViolationCategory, int]]:
        """Get most frequent violation categories for an agent."""
        counter = self._counters.get(agent_id, Counter())
        return counter.most_common(limit)

    def _get_or_create_metrics(self, agent_id: str) -> ViolationMetrics:
        """Get or create metrics for an agent."""
        if agent_id not in self._metrics:
            self._metrics[agent_id] = ViolationMetrics(agent_id=agent_id)
        return self._metrics[agent_id]
