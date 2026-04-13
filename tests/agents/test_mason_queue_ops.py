"""Tests for MasonQueue issue tracking operations."""

from __future__ import annotations

from stronghold.agents.mason_queue import IssueStatus, MasonQueue


class TestAssign:
    def test_assign_creates_queued_record(self) -> None:
        q = MasonQueue()
        record = q.assign(issue_number=1, title="Add caching")
        assert record.issue_number == 1
        assert record.title == "Add caching"
        assert record.status == IssueStatus.QUEUED
        assert record.owner == ""
        assert record.repo == ""
        assert record.error == ""
        assert record.log == []
        assert record.queued_at is not None
        assert record.started_at is None
        assert record.completed_at is None

    def test_assign_with_owner_and_repo(self) -> None:
        q = MasonQueue()
        record = q.assign(
            issue_number=2,
            title="Fix bug",
            owner="mason-bot",
            repo="org/stronghold",
        )
        assert record.owner == "mason-bot"
        assert record.repo == "org/stronghold"

    def test_assign_returns_issue_record(self) -> None:
        from stronghold.agents.mason_queue import IssueRecord

        q = MasonQueue()
        record = q.assign(issue_number=3, title="Task")
        assert isinstance(record, IssueRecord)

    def test_assign_overwrites_existing(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=5, title="Original")
        record = q.assign(issue_number=5, title="Replacement")
        assert record.title == "Replacement"
        assert q.get(5).title == "Replacement"


class TestStart:
    def test_start_sets_in_progress(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=10, title="Work item")
        q.start(10)
        record = q.get(10)
        assert record.status == IssueStatus.IN_PROGRESS
        assert record.started_at is not None

    def test_start_nonexistent_is_noop(self) -> None:
        q = MasonQueue()
        q.start(999)


class TestComplete:
    def test_complete_sets_completed(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=20, title="Build feature")
        q.start(20)
        q.complete(20)
        record = q.get(20)
        assert record.status == IssueStatus.COMPLETED
        assert record.completed_at is not None

    def test_complete_nonexistent_is_noop(self) -> None:
        q = MasonQueue()
        q.complete(999)


class TestFail:
    def test_fail_sets_failed_with_error(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=30, title="Doomed task")
        q.start(30)
        q.fail(30, error="ruff check failed")
        record = q.get(30)
        assert record.status == IssueStatus.FAILED
        assert record.error == "ruff check failed"
        assert record.completed_at is not None

    def test_fail_nonexistent_is_noop(self) -> None:
        q = MasonQueue()
        q.fail(999, error="phantom error")


class TestAddLog:
    def test_add_log_appends_message(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=40, title="Tracked task")
        q.add_log(40, "Step 1: wrote tests")
        q.add_log(40, "Step 2: implementation")
        record = q.get(40)
        assert record.log == ["Step 1: wrote tests", "Step 2: implementation"]

    def test_add_log_nonexistent_is_noop(self) -> None:
        q = MasonQueue()
        q.add_log(999, "ghost log")


class TestGet:
    def test_get_returns_record(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=50, title="Fetchable")
        record = q.get(50)
        assert record is not None
        assert record.issue_number == 50

    def test_get_nonexistent_returns_none(self) -> None:
        q = MasonQueue()
        assert q.get(999) is None


class TestListAll:
    def test_list_all_returns_dicts(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=60, title="First")
        q.assign(issue_number=61, title="Second")
        items = q.list_all()
        assert len(items) == 2
        numbers = {item["issue_number"] for item in items}
        assert numbers == {60, 61}

    def test_list_all_empty(self) -> None:
        q = MasonQueue()
        assert q.list_all() == []

    def test_list_all_dict_shape(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=62, title="Check shape")
        items = q.list_all()
        d = items[0]
        assert "issue_number" in d
        assert "title" in d
        assert "status" in d
        assert "queued_at" in d
        assert "log_lines" in d
        assert d["status"] == "queued"
        assert d["log_lines"] == 0


class TestStatus:
    def test_status_empty_queue(self) -> None:
        q = MasonQueue()
        s = q.status()
        assert s["total"] == 0
        assert s["queued"] == 0
        assert s["in_progress"] == 0
        assert s["completed"] == 0
        assert s["failed"] == 0

    def test_status_counts_by_state(self) -> None:
        q = MasonQueue()
        q.assign(issue_number=70, title="Queued")
        q.assign(issue_number=71, title="Running")
        q.start(71)
        q.assign(issue_number=72, title="Done")
        q.start(72)
        q.complete(72)
        q.assign(issue_number=73, title="Broken")
        q.start(73)
        q.fail(73, error="oops")
        s = q.status()
        assert s["total"] == 4
        assert s["queued"] == 1
        assert s["in_progress"] == 1
        assert s["completed"] == 1
        assert s["failed"] == 1


class TestFullLifecycleSuccess:
    def test_assign_start_complete(self) -> None:
        q = MasonQueue()
        record = q.assign(issue_number=80, title="Full lifecycle")
        assert record.status == IssueStatus.QUEUED
        assert record.started_at is None
        assert record.completed_at is None

        q.start(80)
        record = q.get(80)
        assert record.status == IssueStatus.IN_PROGRESS
        assert record.started_at is not None
        assert record.completed_at is None

        q.complete(80)
        record = q.get(80)
        assert record.status == IssueStatus.COMPLETED
        assert record.completed_at is not None
        assert record.completed_at >= record.started_at


class TestFullLifecycleFailure:
    def test_assign_start_fail(self) -> None:
        q = MasonQueue()
        record = q.assign(issue_number=90, title="Doomed lifecycle")
        assert record.status == IssueStatus.QUEUED

        q.start(90)
        record = q.get(90)
        assert record.status == IssueStatus.IN_PROGRESS

        q.fail(90, error="tests did not pass")
        record = q.get(90)
        assert record.status == IssueStatus.FAILED
        assert record.error == "tests did not pass"
        assert record.completed_at is not None
        assert record.completed_at >= record.started_at
