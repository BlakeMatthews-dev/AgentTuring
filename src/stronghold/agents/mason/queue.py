"""Mason issue queue — tracks assigned issues and their execution status.

Issues flow through: queued -> in_progress -> completed | failed.
The Reactor watcher fires when the queue has pending items.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("stronghold.mason.queue")


class IssueStatus(StrEnum):
    """Status of an assigned issue."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class LogEntry:
    """A single entry in Mason's work log."""

    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class QueuedIssue:
    """An issue assigned to Mason."""

    issue_number: int
    title: str = ""
    owner: str = ""
    repo: str = ""
    status: IssueStatus = IssueStatus.QUEUED
    pr_number: int | None = None
    error: str = ""
    log: list[LogEntry] = field(default_factory=list)
    assigned_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InMemoryMasonQueue:
    """In-memory queue for Mason issue assignments.

    Thread-safe for the single-threaded async event loop.
    """

    def __init__(self) -> None:
        self._issues: dict[int, QueuedIssue] = {}

    def assign(
        self,
        issue_number: int,
        *,
        title: str = "",
        owner: str = "",
        repo: str = "",
    ) -> QueuedIssue:
        """Assign an issue to Mason. Idempotent — re-queues failed issues."""
        existing = self._issues.get(issue_number)
        if existing and existing.status in (IssueStatus.QUEUED, IssueStatus.IN_PROGRESS):
            return existing

        issue = QueuedIssue(
            issue_number=issue_number,
            title=title,
            owner=owner,
            repo=repo,
        )
        self._issues[issue_number] = issue
        logger.info("Issue #%d assigned to Mason: %s", issue_number, title)
        return issue

    def next_pending(self) -> QueuedIssue | None:
        """Get the next queued issue (FIFO)."""
        for issue in self._issues.values():
            if issue.status == IssueStatus.QUEUED:
                return issue
        return None

    def has_pending(self) -> bool:
        """Check if there are pending issues — used by Reactor STATE trigger."""
        return any(i.status == IssueStatus.QUEUED for i in self._issues.values())

    def start(self, issue_number: int) -> None:
        """Mark an issue as in-progress."""
        issue = self._issues.get(issue_number)
        if issue:
            issue.status = IssueStatus.IN_PROGRESS
            issue.started_at = datetime.now(UTC)

    def add_log(self, issue_number: int, message: str) -> None:
        """Append a log entry to an issue's work log."""
        issue = self._issues.get(issue_number)
        if issue:
            issue.log.append(LogEntry(message=message))

    def complete(self, issue_number: int, *, pr_number: int | None = None) -> None:
        """Mark an issue as completed."""
        issue = self._issues.get(issue_number)
        if issue:
            issue.status = IssueStatus.COMPLETED
            issue.pr_number = pr_number
            issue.completed_at = datetime.now(UTC)

    def fail(self, issue_number: int, *, error: str = "") -> None:
        """Mark an issue as failed."""
        issue = self._issues.get(issue_number)
        if issue:
            issue.status = IssueStatus.FAILED
            issue.error = error
            issue.completed_at = datetime.now(UTC)

    def status(self) -> dict[str, Any]:
        """Get queue status summary."""
        counts: dict[str, int] = {}
        for issue in self._issues.values():
            counts[issue.status] = counts.get(issue.status, 0) + 1
        return {
            "total": len(self._issues),
            "counts": counts,
            "current": self._current_issue(),
        }

    def list_all(self) -> list[dict[str, Any]]:
        """List all issues in the queue with full detail."""
        return [
            {
                "issue_number": i.issue_number,
                "title": i.title,
                "status": i.status,
                "pr_number": i.pr_number,
                "error": i.error,
                "log": [
                    {"message": e.message, "time": e.timestamp.isoformat()}
                    for e in i.log
                ],
                "assigned_at": i.assigned_at.isoformat(),
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
                "owner": i.owner,
                "repo": i.repo,
            }
            for i in self._issues.values()
        ]

    def _current_issue(self) -> dict[str, Any] | None:
        for issue in self._issues.values():
            if issue.status == IssueStatus.IN_PROGRESS:
                return {
                    "issue_number": issue.issue_number,
                    "title": issue.title,
                    "started_at": issue.started_at.isoformat() if issue.started_at else None,
                }
        return None
