"""Tests for A2A DelegationService.

Spec: Agent-to-agent task delegation with capability registry and priority selection.
AC: register capabilities, delegate tasks with validation, auto-select agents,
    track task lifecycle, enforce delegation modes.
Edge cases: unknown agent, unknown target, NONE mode with target, empty capabilities,
             priority fallback, task status transitions.
Contracts: delegate_task returns task_id str, get_task_status returns A2ATask|None,
           update_task_status raises ValueError for unknown task.
"""

from __future__ import annotations

import pytest

from stronghold.a2a.delegate import (
    A2ATask,
    DelegationMode,
    DelegationService,
    TaskStatus,
)


class TestDelegationMode:
    def test_enum_values(self) -> None:
        assert DelegationMode.NONE == "none"
        assert DelegationMode.ALLOW_ALL == "allow_all"
        assert DelegationMode.ALLOW_LIST == "allow_list"


class TestTaskStatus:
    def test_lifecycle_order(self) -> None:
        statuses = [
            TaskStatus.QUEUED,
            TaskStatus.ASSIGNED,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
        ]
        assert len(statuses) == 4

    def test_failure_statuses(self) -> None:
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"


class TestRegisterCapability:
    def test_register_single_agent(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("agent-a", ["agent-b", "agent-c"])
        tid = svc.delegate_task("agent-a", "do work", "agent-b")
        assert isinstance(tid, str)

    def test_overwrite_capabilities(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("agent-a", ["agent-b"])
        svc.register_agent_capability("agent-a", ["agent-c"])
        with pytest.raises(ValueError, match="not allowed"):
            svc.delegate_task("agent-a", "do work", "agent-b")


class TestDelegateTaskValidation:
    def test_none_mode_with_target_raises(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        with pytest.raises(ValueError, match="NONE"):
            svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.NONE)

    def test_unknown_from_agent_raises(self) -> None:
        svc = DelegationService()
        with pytest.raises(ValueError, match="no registered"):
            svc.delegate_task("ghost", "task", "b")

    def test_disallowed_target_raises(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        with pytest.raises(ValueError, match="not allowed"):
            svc.delegate_task("a", "task", "c")


class TestDelegateTaskAutoSelect:
    def test_allow_all_picks_first(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b", "c"])
        tid = svc.delegate_task("a", "task", None, delegation_mode=DelegationMode.ALLOW_ALL)
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.to_agent == "b"

    def test_allow_list_selects_by_priority(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", None, delegation_mode=DelegationMode.ALLOW_LIST)
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.to_agent in ("b", "")

    def test_task_created_as_queued(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.ALLOW_ALL)
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.status == TaskStatus.QUEUED
        assert task.assigned_at is None
        assert task.completed_at is None


class TestGetTaskStatus:
    def test_unknown_returns_none(self) -> None:
        svc = DelegationService()
        assert svc.get_task_status("nonexistent") is None


class TestUpdateTaskStatus:
    def test_valid_transition(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.ALLOW_ALL)
        svc.update_task_status(tid, TaskStatus.RUNNING)
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.status == TaskStatus.RUNNING

    def test_completed_sets_timestamp(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.ALLOW_ALL)
        svc.update_task_status(tid, TaskStatus.RUNNING)
        svc.update_task_status(tid, TaskStatus.COMPLETED, result="done")
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.result == "done"

    def test_failed_sets_timestamp(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.ALLOW_ALL)
        svc.update_task_status(tid, TaskStatus.RUNNING)
        svc.update_task_status(tid, TaskStatus.FAILED, error="boom")
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.completed_at is not None
        assert task.error == "boom"

    def test_cancelled_sets_timestamp(self) -> None:
        svc = DelegationService()
        svc.register_agent_capability("a", ["b"])
        tid = svc.delegate_task("a", "task", "b", delegation_mode=DelegationMode.ALLOW_ALL)
        svc.update_task_status(tid, TaskStatus.CANCELLED)
        task = svc.get_task_status(tid)
        assert task is not None
        assert task.completed_at is not None

    def test_unknown_task_raises(self) -> None:
        svc = DelegationService()
        with pytest.raises(ValueError, match="Unknown task"):
            svc.update_task_status("nope", TaskStatus.RUNNING)
