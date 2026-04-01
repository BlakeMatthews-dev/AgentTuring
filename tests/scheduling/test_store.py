"""Tests for InMemoryScheduleStore.

Covers:
- CRUD operations (create, get, list, update, delete)
- org_id scoping (cross-org isolation)
- Max 10 tasks per user enforced
- Cron validation (reject invalid expressions, enforce 15-min minimum interval)
- Execution history tracking
- list_enabled returns only enabled tasks
"""

from __future__ import annotations

import time

import pytest

from stronghold.scheduling.store import (
    InMemoryScheduleStore,
    ScheduledTask,
    TaskExecution,
)


@pytest.fixture
def store() -> InMemoryScheduleStore:
    return InMemoryScheduleStore()


def _make_task(**overrides: object) -> ScheduledTask:
    """Build a ScheduledTask with sensible defaults."""
    defaults: dict[str, object] = {
        "user_id": "user-1",
        "org_id": "org-1",
        "name": "Morning email summary",
        "schedule": "0 8 * * *",
        "prompt": "Summarize my emails from today",
        "agent": "",
        "delivery": "slack:#general",
        "enabled": True,
    }
    defaults.update(overrides)
    return ScheduledTask(**defaults)  # type: ignore[arg-type]


# ── CRUD ─────────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_assigns_id(self, store: InMemoryScheduleStore) -> None:
        task = _make_task()
        created = await store.create(task)
        assert created.id != ""
        assert created.user_id == "user-1"
        assert created.org_id == "org-1"
        assert created.created_at > 0

    async def test_create_preserves_fields(self, store: InMemoryScheduleStore) -> None:
        task = _make_task(name="My task", prompt="Do something", agent="ranger")
        created = await store.create(task)
        assert created.name == "My task"
        assert created.prompt == "Do something"
        assert created.agent == "ranger"


class TestGet:
    async def test_get_existing(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        fetched = await store.get(created.id, org_id="org-1")
        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_nonexistent_returns_none(self, store: InMemoryScheduleStore) -> None:
        result = await store.get("nonexistent", org_id="org-1")
        assert result is None

    async def test_get_wrong_org_returns_none(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(org_id="org-1"))
        result = await store.get(created.id, org_id="org-other")
        assert result is None


class TestListForUser:
    async def test_list_returns_user_tasks(self, store: InMemoryScheduleStore) -> None:
        await store.create(_make_task(user_id="user-1", org_id="org-1"))
        await store.create(_make_task(user_id="user-1", org_id="org-1", name="Second"))
        await store.create(_make_task(user_id="user-2", org_id="org-1"))

        tasks = await store.list_for_user(user_id="user-1", org_id="org-1")
        assert len(tasks) == 2

    async def test_list_respects_org_scope(self, store: InMemoryScheduleStore) -> None:
        await store.create(_make_task(user_id="user-1", org_id="org-1"))
        await store.create(_make_task(user_id="user-1", org_id="org-2"))

        tasks = await store.list_for_user(user_id="user-1", org_id="org-1")
        assert len(tasks) == 1


class TestUpdate:
    async def test_update_fields(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        updated = await store.update(created.id, org_id="org-1", name="Updated name")
        assert updated is not None
        assert updated.name == "Updated name"

    async def test_update_nonexistent_returns_none(self, store: InMemoryScheduleStore) -> None:
        result = await store.update("nope", org_id="org-1", name="x")
        assert result is None

    async def test_update_wrong_org_returns_none(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(org_id="org-1"))
        result = await store.update(created.id, org_id="org-other", name="x")
        assert result is None

    async def test_update_enable_disable(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        updated = await store.update(created.id, org_id="org-1", enabled=False)
        assert updated is not None
        assert updated.enabled is False


class TestDelete:
    async def test_delete_existing(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        assert await store.delete(created.id, org_id="org-1") is True
        assert await store.get(created.id, org_id="org-1") is None

    async def test_delete_nonexistent_returns_false(self, store: InMemoryScheduleStore) -> None:
        assert await store.delete("nope", org_id="org-1") is False

    async def test_delete_wrong_org_returns_false(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(org_id="org-1"))
        assert await store.delete(created.id, org_id="org-other") is False


# ── Constraints ──────────────────────────────────────────────────────


class TestMaxTasksPerUser:
    async def test_rejects_over_10_tasks(self, store: InMemoryScheduleStore) -> None:
        for i in range(10):
            await store.create(
                _make_task(user_id="user-1", org_id="org-1", name=f"Task {i}")
            )
        with pytest.raises(ValueError, match="maximum.*10"):
            await store.create(
                _make_task(user_id="user-1", org_id="org-1", name="Task 11")
            )

    async def test_different_users_have_separate_limits(
        self, store: InMemoryScheduleStore
    ) -> None:
        for i in range(10):
            await store.create(
                _make_task(user_id="user-1", org_id="org-1", name=f"Task {i}")
            )
        # user-2 should still be able to create tasks
        created = await store.create(
            _make_task(user_id="user-2", org_id="org-1", name="User 2 task")
        )
        assert created.id != ""


class TestCronValidation:
    async def test_rejects_invalid_cron(self, store: InMemoryScheduleStore) -> None:
        with pytest.raises(ValueError, match="[Ii]nvalid cron"):
            await store.create(_make_task(schedule="not a cron"))

    async def test_rejects_too_frequent_cron(self, store: InMemoryScheduleStore) -> None:
        """Minimum interval is 15 minutes — every-minute cron must be rejected."""
        with pytest.raises(ValueError, match="15 min"):
            await store.create(_make_task(schedule="* * * * *"))

    async def test_accepts_valid_hourly_cron(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(schedule="0 * * * *"))
        assert created.schedule == "0 * * * *"

    async def test_accepts_every_15_minutes(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(schedule="*/15 * * * *"))
        assert created.schedule == "*/15 * * * *"


# ── Execution History ────────────────────────────────────────────────


class TestExecutionHistory:
    async def test_record_and_get_history(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        exec1 = TaskExecution(
            id="exec-1",
            task_id=created.id,
            started_at=time.time(),
            completed_at=time.time() + 5,
            status="success",
            result_preview="Summary: 3 important emails...",
        )
        await store.record_execution(created.id, exec1)
        history = await store.get_history(created.id, org_id="org-1")
        assert len(history) == 1
        assert history[0].status == "success"

    async def test_history_respects_limit(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task())
        for i in range(15):
            await store.record_execution(
                created.id,
                TaskExecution(id=f"exec-{i}", task_id=created.id, status="success"),
            )
        history = await store.get_history(created.id, org_id="org-1", limit=5)
        assert len(history) == 5

    async def test_history_wrong_org_returns_empty(self, store: InMemoryScheduleStore) -> None:
        created = await store.create(_make_task(org_id="org-1"))
        await store.record_execution(
            created.id,
            TaskExecution(id="exec-1", task_id=created.id, status="success"),
        )
        history = await store.get_history(created.id, org_id="org-other")
        assert history == []


# ── list_enabled ─────────────────────────────────────────────────────


class TestListEnabled:
    async def test_returns_only_enabled_tasks(self, store: InMemoryScheduleStore) -> None:
        await store.create(_make_task(name="Active", enabled=True))
        task2 = await store.create(_make_task(name="Disabled", enabled=True))
        await store.update(task2.id, org_id="org-1", enabled=False)

        enabled = await store.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "Active"
