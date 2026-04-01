"""Tests for InMemoryViolationTracker.

Verifies violation counting, metrics computation, and trend analysis.
"""

from __future__ import annotations

from stronghold.agents.feedback.tracker import InMemoryViolationTracker
from stronghold.types.feedback import (
    ReviewFinding,
    ReviewResult,
    Severity,
    ViolationCategory,
    ViolationMetrics,
)


def _finding(
    category: ViolationCategory = ViolationCategory.MOCK_USAGE,
) -> ReviewFinding:
    return ReviewFinding(
        category=category,
        severity=Severity.HIGH,
        file_path="tests/test_foo.py",
        description="test finding",
        suggestion="fix it",
    )


def _review(
    *findings: ReviewFinding,
    agent_id: str = "mason",
    pr_number: int = 1,
) -> ReviewResult:
    return ReviewResult(
        pr_number=pr_number,
        agent_id=agent_id,
        findings=tuple(findings),
        approved=len(findings) == 0,
        summary="test review",
    )


class TestRecordFinding:
    """Individual finding recording."""

    def test_records_finding_for_agent(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_finding(_finding(), agent_id="mason")
        metrics = tracker.get_metrics("mason")
        assert metrics.total_findings == 1

    def test_increments_category_count(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_finding(_finding(ViolationCategory.MOCK_USAGE), agent_id="mason")
        tracker.record_finding(_finding(ViolationCategory.MOCK_USAGE), agent_id="mason")
        metrics = tracker.get_metrics("mason")
        assert metrics.category_counts[ViolationCategory.MOCK_USAGE] == 2

    def test_separate_agents_separate_counts(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_finding(_finding(), agent_id="mason")
        tracker.record_finding(_finding(), agent_id="other")
        assert tracker.get_metrics("mason").total_findings == 1
        assert tracker.get_metrics("other").total_findings == 1


class TestRecordReview:
    """Complete review recording."""

    def test_increments_pr_count(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_review(_review(_finding()))
        metrics = tracker.get_metrics("mason")
        assert metrics.total_prs_reviewed == 1

    def test_records_all_findings(self) -> None:
        tracker = InMemoryViolationTracker()
        review = _review(
            _finding(ViolationCategory.MOCK_USAGE),
            _finding(ViolationCategory.ARCHITECTURE_UPDATE),
        )
        tracker.record_review(review)
        metrics = tracker.get_metrics("mason")
        assert metrics.total_findings == 2

    def test_updates_findings_per_pr_history(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_review(_review(_finding(), _finding(), _finding()))
        tracker.record_review(_review(_finding()))
        metrics = tracker.get_metrics("mason")
        assert metrics.findings_per_pr_history == [3.0, 1.0]


class TestGetTopViolations:
    """Most frequent violation categories."""

    def test_returns_most_common(self) -> None:
        tracker = InMemoryViolationTracker()
        for _ in range(5):
            tracker.record_finding(_finding(ViolationCategory.MOCK_USAGE), agent_id="mason")
        for _ in range(3):
            tracker.record_finding(
                _finding(ViolationCategory.ARCHITECTURE_UPDATE), agent_id="mason"
            )
        tracker.record_finding(_finding(ViolationCategory.SECURITY), agent_id="mason")

        top = tracker.get_top_violations("mason", limit=2)
        assert len(top) == 2
        assert top[0] == (ViolationCategory.MOCK_USAGE, 5)
        assert top[1] == (ViolationCategory.ARCHITECTURE_UPDATE, 3)

    def test_empty_for_unknown_agent(self) -> None:
        tracker = InMemoryViolationTracker()
        top = tracker.get_top_violations("unknown")
        assert top == []


class TestViolationMetrics:
    """Metrics computation — findings_per_pr and trend."""

    def test_findings_per_pr_zero_when_no_reviews(self) -> None:
        metrics = ViolationMetrics(agent_id="mason")
        assert metrics.findings_per_pr == 0.0

    def test_findings_per_pr_computed(self) -> None:
        metrics = ViolationMetrics(
            agent_id="mason", total_prs_reviewed=10, total_findings=30
        )
        assert metrics.findings_per_pr == 3.0

    def test_trend_insufficient_data(self) -> None:
        metrics = ViolationMetrics(
            agent_id="mason", findings_per_pr_history=[5.0, 3.0]
        )
        assert metrics.trend == "insufficient_data"

    def test_trend_improving(self) -> None:
        # Older: [5, 5, 5], Recent: [2, 1, 1] -> improving
        metrics = ViolationMetrics(
            agent_id="mason",
            findings_per_pr_history=[5.0, 5.0, 5.0, 2.0, 1.0, 1.0],
        )
        assert metrics.trend == "improving"

    def test_trend_regressing(self) -> None:
        # Older: [1, 1, 1], Recent: [5, 5, 5] -> regressing
        metrics = ViolationMetrics(
            agent_id="mason",
            findings_per_pr_history=[1.0, 1.0, 1.0, 5.0, 5.0, 5.0],
        )
        assert metrics.trend == "regressing"

    def test_trend_stable(self) -> None:
        # Older: [3, 3, 3], Recent: [3, 3, 3] -> stable
        metrics = ViolationMetrics(
            agent_id="mason",
            findings_per_pr_history=[3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        )
        assert metrics.trend == "stable"
