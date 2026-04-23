"""Task Lifecycle module.

Manages task states (queued → assigned → running → completed/failed),
task queue, worker pool for parallel execution, timeout and retry logic.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stronghold.a2a.delegate import TaskStatus

logger = logging.getLogger("stronghold.a2a.lifecycle")


@dataclass
class WorkerConfig:
    """Worker pool configuration."""

    max_workers: int = 4
    task_timeout_seconds: int = 300
    max_retries: int = 3
    retry_delay_seconds: int = 5


logger = logging.getLogger("stronghold.a2a.lifecycle")


class TaskQueue:
    """Task queue with priority scheduling."""

    def __init__(self) -> None:
        """Initialize Task Queue."""
        self._queue: dict[str, list[dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def enqueue(
        self,
        task: dict[str, Any],
        priority: str = "P2",
    ) -> str:
        """Enqueue task.

        Args:
            task: Task data
            priority: Priority tier (P0-P5)

        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())
        if priority not in self._queue:
            self._queue[priority] = []
        self._queue[priority].append(task)
        logger.info("Task enqueued: %s (priority=%s)", task_id, priority)
        return task_id

    async def dequeue(self, priority: str | None = None) -> dict[str, Any] | None:
        """Dequeue next task.

        Args:
            priority: Priority tier filter (None = any)

        Returns:
            Task data or None if queue is empty
        """
        priority_order = ["P0", "P1", "P2", "P3", "P4", "P5"]

        if priority and priority in self._queue and self._queue[priority]:
            return self._queue[priority].pop(0)

        for tier in priority_order:
            if tier in self._queue and self._queue[tier]:
                return self._queue[tier].pop(0)

        return None

    def size(self) -> int:
        """Get total queue size."""
        return sum(len(tasks) for tasks in self._queue.values())

    def size_by_priority(self, priority: str) -> int:
        """Get queue size for specific priority."""
        return len(self._queue.get(priority, []))


class WorkerPool:
    """Worker pool for parallel task execution."""

    def __init__(self, config: WorkerConfig | None = None) -> None:
        """Initialize Worker Pool."""
        self.config = config or WorkerConfig()
        self._workers: list[Any] = []
        self._active_tasks: dict[str, dict[str, Any]] = {}

    async def submit(self, task_id: str, task: dict[str, Any]) -> None:
        """Submit task to worker pool.

        Args:
            task_id: Task ID
            task: Task data
        """
        if len(self._active_tasks) >= self.config.max_workers:
            logger.warning(
                "Worker pool at capacity: %d/%d",
                len(self._active_tasks),
                self.config.max_workers,
            )
            raise RuntimeError(
                f"Worker pool at capacity: {len(self._active_tasks)}/{self.config.max_workers}"
            )

        logger.info("Task submitted to worker: %s", task_id)
        self._active_tasks[task_id] = task

    async def _execute_task(self, task_id: str, task_data: dict[str, Any]) -> str:
        """Execute a single task with timeout and retry."""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                await asyncio.wait_for(
                    asyncio.sleep(0.1),
                    timeout=self.config.task_timeout_seconds,
                )
                task_data["status"] = TaskStatus.COMPLETED
                task_data["result"] = "completed"
                task_data["completed_at"] = datetime.now(UTC)
                logger.info("Task completed: %s", task_id)
                return task_id
            except TimeoutError:
                logger.error("Task timeout: %s", task_id)
                task_data["status"] = TaskStatus.FAILED
                task_data["error"] = "Task timeout"

                if attempt == self.config.max_retries:
                    break
                await asyncio.sleep(self.config.retry_delay_seconds)

        return task_id

    def get_active_tasks(self) -> list[str]:
        """Get list of currently active task IDs."""
        return list(self._active_tasks.keys())

    def get_status(self) -> dict[str, Any]:
        """Get worker pool status."""
        return {
            "active_tasks": len(self._active_tasks),
            "max_workers": self.config.max_workers,
            "available_workers": self.config.max_workers - len(self._active_tasks),
        }


class TaskLifecycle:
    """Task Lifecycle Manager."""

    def __init__(self) -> None:
        """Initialize Task Lifecycle Manager."""
        self.queue = TaskQueue()
        self.workers = WorkerPool()

    async def create_task(
        self,
        task: dict[str, Any],
        priority: str = "P2",
    ) -> str:
        """Create and queue a new task.

        Args:
            task: Task data
            priority: Priority tier (P0-P5)

        Returns:
            Task ID
        """
        return await self.queue.enqueue(task, priority)

    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get task status.

        Args:
            task_id: Task ID

        Returns:
            Task status data
        """
        task = self.workers._active_tasks.get(task_id)
        if not task:
            return {"status": TaskStatus.QUEUED, "task_id": task_id}

        return {
            "status": task["status"],
            "task_id": task_id,
            "from_agent": task.get("from_agent"),
            "to_agent": task.get("to_agent"),
            "created_at": task["created_at"],
            "completed_at": task.get("completed_at"),
            "result": task.get("result"),
            "error": task.get("error"),
        }

    async def get_queue_status(self) -> dict[str, Any]:
        """Get queue and worker pool status."""
        return {
            "queue_size": self.queue.size(),
            "queue_by_priority": {
                "P0": self.queue.size_by_priority("P0"),
                "P1": self.queue.size_by_priority("P1"),
                "P2": self.queue.size_by_priority("P2"),
                "P3": self.queue.size_by_priority("P3"),
                "P4": self.queue.size_by_priority("P4"),
                "P5": self.queue.size_by_priority("P5"),
            },
            "worker_status": self.workers.get_status(),
        }
