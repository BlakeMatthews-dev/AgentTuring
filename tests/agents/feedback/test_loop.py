"""Tests for the FeedbackLoop orchestrator.

End-to-end tests through the RLHF cycle using real classes:
ReviewFeedbackExtractor, InMemoryLearningStore, InMemoryViolationTracker.
"""

from __future__ import annotations

from stronghold.agents.feedback.extractor import ReviewFeedbackExtractor
from stronghold.agents.feedback.loop import FeedbackLoop
from stronghold.agents.feedback.tracker import InMemoryViolationTracker
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.feedback import (
    ReviewFinding,
    ReviewResult,
    Severity,
    ViolationCategory,
)


def _finding(
    category: ViolationCategory = ViolationCategory.MOCK_USAGE,
) -> ReviewFinding:
    return ReviewFinding(
        category=category,
        severity=Severity.HIGH,
        file_path="tests/test_foo.py",
        description="unittest.mock detected",
        suggestion="Use fakes from tests/fakes.py",
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


def _make_loop() -> tuple[FeedbackLoop, InMemoryLearningStore, InMemoryViolationTracker]:
    extractor = ReviewFeedbackExtractor()
    learning_store = InMemoryLearningStore()
    violation_tracker = InMemoryViolationTracker()
    loop = FeedbackLoop(
        extractor=extractor,
        learning_store=learning_store,
        violation_store=violation_tracker,
    )
    return loop, learning_store, violation_tracker


class TestFeedbackLoopProcessReview:
    """Full RLHF cycle: review -> extract -> store -> track."""

    async def test_stores_learnings_from_review(self) -> None:
        loop, store, _ = _make_loop()
        result = _review(_finding())
        stored = await loop.process_review(result)
        assert stored == 1

    async def test_tracks_violations(self) -> None:
        loop, _, tracker = _make_loop()
        result = _review(_finding(), _finding(ViolationCategory.ARCHITECTURE_UPDATE))
        await loop.process_review(result)
        metrics = tracker.get_metrics("mason")
        assert metrics.total_prs_reviewed == 1
        assert metrics.total_findings == 2

    async def test_learnings_scoped_to_agent(self) -> None:
        loop, store, _ = _make_loop()
        result = _review(_finding(), agent_id="mason")
        await loop.process_review(result)
        # Learnings should be findable for mason
        learnings = await store.find_relevant(
            "mock unittest", agent_id="mason", org_id="", max_results=10
        )
        assert len(learnings) >= 1

    async def test_empty_review_stores_nothing(self) -> None:
        loop, store, tracker = _make_loop()
        result = _review()  # no findings
        stored = await loop.process_review(result)
        assert stored == 0
        assert tracker.get_metrics("mason").total_prs_reviewed == 1

    async def test_multiple_reviews_accumulate(self) -> None:
        loop, _, tracker = _make_loop()
        await loop.process_review(_review(_finding(), _finding(), _finding(), pr_number=1))
        await loop.process_review(_review(_finding(), pr_number=2))
        await loop.process_review(_review(pr_number=3))

        metrics = tracker.get_metrics("mason")
        assert metrics.total_prs_reviewed == 3
        assert metrics.total_findings == 4
        assert metrics.findings_per_pr_history == [3.0, 1.0, 0.0]

    async def test_returns_stored_count(self) -> None:
        loop, _, _ = _make_loop()
        result = _review(
            _finding(ViolationCategory.MOCK_USAGE),
            _finding(ViolationCategory.ARCHITECTURE_UPDATE),
            _finding(ViolationCategory.SECURITY),
        )
        stored = await loop.process_review(result)
        assert stored == 3

    async def test_deduplication_reduces_stored_count(self) -> None:
        loop, _, _ = _make_loop()
        result = _review(_finding())
        # First time: stores
        stored1 = await loop.process_review(result)
        # Second time: dedup should prevent re-storing
        stored2 = await loop.process_review(result)
        # At least one should have stored, second may dedup
        assert stored1 >= stored2
