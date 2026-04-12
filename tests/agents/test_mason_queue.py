"""Tests for MasonQueue — in-memory issue queue for Mason builder agent."""

from __future__ import annotations

from stronghold.agents.mason_queue import IssueRecord, IssueStatus, MasonQueue


class TestIssueStatus:
    """IssueStatus enum values."""

    def test_enum_values(self):
        assert IssueStatus.QUEUED.value == "queued"
        assert IssueStatus.IN_PROGRESS.value == "in_progress"
        assert IssueStatus.COMPLETED.value == "completed"
        assert IssueStatus.FAILED.value == "failed"


class TestIssueRecord:
    """IssueRecord dataclass and serialization."""

    def test_defaults(self):
        record = IssueRecord(issue_number=1, title="Fix bug")
        assert record.issue_number == 1
        assert record.title == "Fix bug"
        assert record.owner == ""
        assert record.repo == ""
        assert record.status is IssueStatus.QUEUED
        assert record.error == ""
        assert record.log == []
        assert record.queued_at is not None
        assert record.started_at is None
        assert record.completed_at is None

    def test_to_dict_basic(self):
        record = IssueRecord(issue_number=42, title="Add feature", owner="org", repo="repo")
        d = record.to_dict()
        assert d["issue_number"] == 42
        assert d["title"] == "Add feature"
        assert d["owner"] == "org"
        assert d["repo"] == "repo"
        assert d["status"] == "queued"
        assert d["error"] == ""
        assert d["log_lines"] == 0
        assert isinstance(d["queued_at"], str)
        assert d["started_at"] is None
        assert d["completed_at"] is None

    def test_to_dict_with_timestamps(self):
        record = IssueRecord(issue_number=1, title="t")
        from datetime import UTC, datetime

        record.started_at = datetime(2026, 1, 1, tzinfo=UTC)
        record.completed_at = datetime(2026, 1, 2, tzinfo=UTC)
        d = record.to_dict()
        assert d["started_at"] is not None
        assert "2026" in d["started_at"]
        assert d["completed_at"] is not None
        assert "2026" in d["completed_at"]

    def test_to_dict_log_lines_count(self):
        record = IssueRecord(issue_number=1, title="t")
        record.log.append("step 1")
        record.log.append("step 2")
        d = record.to_dict()
        assert d["log_lines"] == 2


class TestMasonQueueAssign:
    """MasonQueue.assign() creates and stores issue records."""

    def test_assign_returns_record(self):
        q = MasonQueue()
        record = q.assign(10, "Test issue", owner="org", repo="repo")
        assert isinstance(record, IssueRecord)
        assert record.issue_number == 10
        assert record.title == "Test issue"
        assert record.owner == "org"
        assert record.repo == "repo"
        assert record.status is IssueStatus.QUEUED

    def test_assign_stores_record(self):
        q = MasonQueue()
        q.assign(10, "Test issue")
        assert q.get(10) is not None

    def test_assign_overwrites_existing(self):
        q = MasonQueue()
        q.assign(10, "First")
        q.assign(10, "Second")
        assert q.get(10).title == "Second"


class TestMasonQueueStart:
    """MasonQueue.start() transitions to IN_PROGRESS."""

    def test_start_sets_status_and_timestamp(self):
        q = MasonQueue()
        q.assign(1, "Issue")
        q.start(1)
        record = q.get(1)
        assert record.status is IssueStatus.IN_PROGRESS
        assert record.started_at is not None

    def test_start_missing_issue_is_noop(self):
        q = MasonQueue()
        q.start(999)  # should not raise


class TestMasonQueueComplete:
    """MasonQueue.complete() transitions to COMPLETED."""

    def test_complete_sets_status_and_timestamp(self):
        q = MasonQueue()
        q.assign(1, "Issue")
        q.start(1)
        q.complete(1)
        record = q.get(1)
        assert record.status is IssueStatus.COMPLETED
        assert record.completed_at is not None

    def test_complete_missing_issue_is_noop(self):
        q = MasonQueue()
        q.complete(999)  # should not raise


class TestMasonQueueFail:
    """MasonQueue.fail() transitions to FAILED with error."""

    def test_fail_sets_status_error_and_timestamp(self):
        q = MasonQueue()
        q.assign(1, "Issue")
        q.start(1)
        q.fail(1, "timeout")
        record = q.get(1)
        assert record.status is IssueStatus.FAILED
        assert record.error == "timeout"
        assert record.completed_at is not None

    def test_fail_missing_issue_is_noop(self):
        q = MasonQueue()
        q.fail(999, "err")  # should not raise


class TestMasonQueueAddLog:
    """MasonQueue.add_log() appends log messages."""

    def test_add_log_appends(self):
        q = MasonQueue()
        q.assign(1, "Issue")
        q.add_log(1, "step 1")
        q.add_log(1, "step 2")
        record = q.get(1)
        assert record.log == ["step 1", "step 2"]

    def test_add_log_missing_issue_is_noop(self):
        q = MasonQueue()
        q.add_log(999, "msg")  # should not raise


class TestMasonQueueGet:
    """MasonQueue.get() retrieves or returns None."""

    def test_get_existing(self):
        q = MasonQueue()
        q.assign(1, "Issue")
        assert q.get(1) is not None

    def test_get_missing(self):
        q = MasonQueue()
        assert q.get(999) is None


class TestMasonQueueListAll:
    """MasonQueue.list_all() returns serialized records."""

    def test_list_all_empty(self):
        q = MasonQueue()
        assert q.list_all() == []

    def test_list_all_multiple(self):
        q = MasonQueue()
        q.assign(1, "First")
        q.assign(2, "Second")
        items = q.list_all()
        assert len(items) == 2
        numbers = {item["issue_number"] for item in items}
        assert numbers == {1, 2}


class TestMasonQueueStatus:
    """MasonQueue.status() returns aggregated counts."""

    def test_status_empty(self):
        q = MasonQueue()
        s = q.status()
        assert s["total"] == 0
        assert s["queued"] == 0
        assert s["in_progress"] == 0
        assert s["completed"] == 0
        assert s["failed"] == 0

    def test_status_mixed(self):
        q = MasonQueue()
        q.assign(1, "A")
        q.assign(2, "B")
        q.assign(3, "C")
        q.assign(4, "D")
        q.start(2)
        q.complete(3)
        q.fail(4, "err")
        s = q.status()
        assert s["total"] == 4
        assert s["queued"] == 1
        assert s["in_progress"] == 1
        assert s["completed"] == 1
        assert s["failed"] == 1
