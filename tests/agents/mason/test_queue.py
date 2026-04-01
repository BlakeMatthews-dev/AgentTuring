"""Tests for InMemoryMasonQueue.

Uses real classes, no mocks.
"""

from __future__ import annotations

from stronghold.agents.mason.queue import (
    InMemoryMasonQueue,
    IssueStatus,
)


class TestAssign:
    """Issue assignment."""

    def test_assigns_issue(self) -> None:
        queue = InMemoryMasonQueue()
        issue = queue.assign(42, title="Fix bug", owner="org", repo="repo")
        assert issue.issue_number == 42
        assert issue.status == IssueStatus.QUEUED

    def test_idempotent_when_queued(self) -> None:
        queue = InMemoryMasonQueue()
        first = queue.assign(42, title="Fix bug")
        second = queue.assign(42, title="Fix bug again")
        assert first is second

    def test_requeues_failed(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42, title="Fix bug")
        queue.fail(42, error="broke")
        requeued = queue.assign(42, title="Fix bug")
        assert requeued.status == IssueStatus.QUEUED


class TestNextPending:
    """FIFO queue behavior."""

    def test_returns_first_queued(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(1, title="First")
        queue.assign(2, title="Second")
        nxt = queue.next_pending()
        assert nxt is not None
        assert nxt.issue_number == 1

    def test_returns_none_when_empty(self) -> None:
        queue = InMemoryMasonQueue()
        assert queue.next_pending() is None

    def test_skips_in_progress(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(1, title="First")
        queue.assign(2, title="Second")
        queue.start(1)
        nxt = queue.next_pending()
        assert nxt is not None
        assert nxt.issue_number == 2


class TestHasPending:
    """STATE trigger condition."""

    def test_false_when_empty(self) -> None:
        queue = InMemoryMasonQueue()
        assert not queue.has_pending()

    def test_true_when_queued(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42)
        assert queue.has_pending()

    def test_false_when_all_complete(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42)
        queue.start(42)
        queue.complete(42)
        assert not queue.has_pending()


class TestLifecycle:
    """Full issue lifecycle: queued -> in_progress -> completed."""

    def test_full_lifecycle(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42, title="Fix bug")
        assert queue.next_pending() is not None

        queue.start(42)
        issue = queue._issues[42]
        assert issue.status == IssueStatus.IN_PROGRESS
        assert issue.started_at is not None

        queue.complete(42, pr_number=99)
        assert issue.status == IssueStatus.COMPLETED
        assert issue.pr_number == 99
        assert issue.completed_at is not None

    def test_failure_records_error(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42)
        queue.start(42)
        queue.fail(42, error="quality gates failed")
        issue = queue._issues[42]
        assert issue.status == IssueStatus.FAILED
        assert issue.error == "quality gates failed"


class TestStatus:
    """Queue status summary."""

    def test_empty_queue(self) -> None:
        queue = InMemoryMasonQueue()
        status = queue.status()
        assert status["total"] == 0
        assert status["current"] is None

    def test_shows_current_issue(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(42, title="Fix bug")
        queue.start(42)
        status = queue.status()
        assert status["current"] is not None
        assert status["current"]["issue_number"] == 42

    def test_counts_by_status(self) -> None:
        queue = InMemoryMasonQueue()
        queue.assign(1)
        queue.assign(2)
        queue.assign(3)
        queue.start(1)
        queue.complete(1)
        status = queue.status()
        assert status["counts"]["completed"] == 1
        assert status["counts"]["queued"] == 2
