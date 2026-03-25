"""Task queue: API submits tasks, Worker claims and processes them.

In-memory implementation for testing. PostgreSQL version uses a tasks table
with status: pending → working → completed/failed.
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Any


class InMemoryTaskQueue:
    """In-memory task queue. PostgreSQL version for production."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._pending: deque[str] = deque()

    async def submit(self, payload: dict[str, Any]) -> str:
        """Submit a task. Returns task_id."""
        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = {
            "id": task_id,
            "status": "pending",
            "payload": payload,
            "result": None,
            "error": None,
        }
        self._pending.append(task_id)
        return task_id

    async def claim(self) -> dict[str, Any] | None:
        """Claim the next pending task. Returns None if empty."""
        while self._pending:
            task_id = self._pending.popleft()
            task = self._tasks.get(task_id)
            if task and task["status"] == "pending":
                task["status"] = "working"
                return task
        return None

    async def complete(self, task_id: str, result: dict[str, Any]) -> None:
        """Mark a task as completed with result."""
        task = self._tasks.get(task_id)
        if task:
            task["status"] = "completed"
            task["result"] = result

    async def fail(self, task_id: str, error: str) -> None:
        """Mark a task as failed with error message."""
        task = self._tasks.get(task_id)
        if task:
            task["status"] = "failed"
            task["error"] = error

    async def get(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID."""
        return self._tasks.get(task_id)

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        return tasks[:limit]
