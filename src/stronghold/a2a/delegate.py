"""A2A (Agent-to-Agent) delegation module.

Handles task delegation between agents, delegation modes,
sub-agent routing, and task status tracking.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("stronghold.a2a.delegate")


class DelegationMode(StrEnum):
    """Delegation mode."""

    NONE = "none"
    ALLOW_ALL = "allow_all"
    ALLOW_LIST = "allow_list"


class TaskStatus(StrEnum):
    """Task status."""

    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class A2ATask:
    """A2A task for delegation."""

    id: str
    from_agent: str
    to_agent: str
    task: str
    status: TaskStatus
    created_at: datetime
    assigned_at: datetime | None
    completed_at: datetime | None
    result: str | None
    error: str | None
    delegation_mode: DelegationMode


class DelegationService:
    """A2A Delegation Service.

    Manages task delegation between agents with configurable
    delegation modes and sub-agent routing.
    """

    def __init__(self) -> None:
        """Initialize Delegation Service."""
        self._tasks: dict[str, A2ATask] = {}
        self._agent_capabilities: dict[str, list[str]] = {}

    def register_agent_capability(self, agent_name: str, can_delegate_to: list[str]) -> None:
        """Register agent's delegation capabilities.

        Args:
            agent_name: Name of agent
            can_delegate_to: List of agent names this agent can delegate to
        """
        self._agent_capabilities[agent_name] = can_delegate_to
        logger.info(
            "Registered delegation capability: %s can delegate to %s", agent_name, can_delegate_to
        )

    def delegate_task(
        self,
        from_agent: str,
        task: str,
        to_agent: str | None,
        delegation_mode: DelegationMode = DelegationMode.NONE,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Delegate a task to another agent.

        Args:
            from_agent: Agent delegating the task
            task: Task description
            to_agent: Target agent (None = auto-select)
            delegation_mode: How delegation should work
            metadata: Additional metadata

        Returns:
            Task ID

        Raises:
            ValueError: If delegation not allowed or invalid
        """
        if delegation_mode == DelegationMode.NONE and to_agent:
            raise ValueError("Cannot specify to_agent with delegation_mode=NONE")

        capabilities = self._agent_capabilities.get(from_agent, [])
        if not capabilities:
            raise ValueError(f"Agent {from_agent} has no delegation capabilities")

        if to_agent and to_agent not in capabilities:
            raise ValueError(
                f"Agent {from_agent} cannot delegate to {to_agent}. Allowed: {capabilities}"
            )

        if not to_agent:
            to_agent = self._select_best_agent(from_agent, task, delegation_mode)

        task_id = str(uuid.uuid4())

        task_obj = A2ATask(
            id=task_id,
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            status=TaskStatus.QUEUED,
            created_at=datetime.now(UTC),
            assigned_at=None,
            completed_at=None,
            result=None,
            error=None,
            delegation_mode=delegation_mode,
        )

        self._tasks[task_id] = task_obj
        logger.info(
            "Task delegated: %s from %s to %s (mode=%s)",
            from_agent,
            task_id,
            to_agent,
            delegation_mode,
        )
        return task_id

    def _select_best_agent(self, from_agent: str, task: str, mode: DelegationMode) -> str:
        """Select best agent for delegation based on mode.

        Args:
            from_agent: Agent delegating
            task: Task description
            mode: Delegation mode

        Returns:
            Selected agent name
        """
        capabilities = self._agent_capabilities.get(from_agent, [])
        if not capabilities:
            return from_agent

        if mode == DelegationMode.ALLOW_ALL:
            return capabilities[0] if capabilities else from_agent

        if mode == DelegationMode.ALLOW_LIST:
            return self._select_from_priority(capabilities)

        return capabilities[0] if capabilities else from_agent

    def _select_from_priority(self, agents: list[str]) -> str:
        """Select agent from list based on priority tier.

        Args:
            agents: List of agent names

        Returns:
            Agent name (P0 preferred)
        """
        priority_order = ["P0", "P1", "P2", "P3", "P4", "P5"]
        for tier in priority_order:
            for agent in agents:
                if agent in self._agent_capabilities and self._agent_capabilities[agent] == [tier]:
                    return agent
        return agents[0] if agents else ""

    def get_task_status(self, task_id: str) -> A2ATask | None:
        """Get task status.

        Args:
            task_id: Task ID

        Returns:
            A2ATask object or None if not found
        """
        return self._tasks.get(task_id)

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update task status.

        Args:
            task_id: Task ID
            status: New status
            result: Task result
            error: Task error
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        old_status = task.status

        if old_status == TaskStatus.RUNNING and status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(UTC)
        elif status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = datetime.now(UTC)
            task.error = error

        task.status = status
        task.result = result

        logger.info("Task status updated: %s %s -> %s", task_id, old_status, status)
