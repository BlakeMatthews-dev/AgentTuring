"""Mason issue queue — tracks issues assigned to the builder agent.

Simple in-memory queue. Stronghold dispatches issues here; the reactor
trigger dequeues and routes them through the Conduit pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger("stronghold.agents.mason_queue")


class IssueStatus(Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IssueRecord:
    issue_number: int
    title: str
    owner: str = ""
    repo: str = ""
    status: IssueStatus = IssueStatus.QUEUED
    error: str = ""
    log: list[str] = field(default_factory=list)
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "title": self.title,
            "owner": self.owner,
            "repo": self.repo,
            "status": self.status.value,
            "error": self.error,
            "log_lines": len(self.log),
            "queued_at": self.queued_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class MasonQueue:
    """In-memory issue queue for the Mason builder agent."""

    def __init__(self) -> None:
        self._issues: dict[int, IssueRecord] = {}

    def assign(
        self,
        issue_number: int,
        title: str,
        owner: str = "",
        repo: str = "",
    ) -> IssueRecord:
        record = IssueRecord(
            issue_number=issue_number,
            title=title,
            owner=owner,
            repo=repo,
        )
        self._issues[issue_number] = record
        logger.info("Issue #%d queued: %s", issue_number, title)
        return record

    def start(self, issue_number: int) -> None:
        record = self._issues.get(issue_number)
        if record:
            record.status = IssueStatus.IN_PROGRESS
            record.started_at = datetime.now(UTC)
            logger.info("Issue #%d started", issue_number)

    def complete(self, issue_number: int) -> None:
        record = self._issues.get(issue_number)
        if record:
            record.status = IssueStatus.COMPLETED
            record.completed_at = datetime.now(UTC)
            logger.info("Issue #%d completed", issue_number)

    def fail(self, issue_number: int, error: str) -> None:
        record = self._issues.get(issue_number)
        if record:
            record.status = IssueStatus.FAILED
            record.error = error
            record.completed_at = datetime.now(UTC)
            logger.warning("Issue #%d failed: %s", issue_number, error)

    def add_log(self, issue_number: int, message: str) -> None:
        record = self._issues.get(issue_number)
        if record:
            record.log.append(message)

    def get(self, issue_number: int) -> IssueRecord | None:
        return self._issues.get(issue_number)

    def list_all(self) -> list[dict[str, object]]:
        return [r.to_dict() for r in self._issues.values()]

    def status(self) -> dict[str, object]:
        counts = {"queued": 0, "in_progress": 0, "completed": 0, "failed": 0}
        for r in self._issues.values():
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        return {"total": len(self._issues), **counts}
