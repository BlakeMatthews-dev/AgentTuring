"""User-scheduled recurring tasks — store and data types.

Constraints:
- Max 10 tasks per user
- Minimum schedule interval: 15 minutes (validated via cron expression)
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# ── Cron validation ──────────────────────────────────────────────────

# Supported cron format: "min hour dom month dow" (5 fields)
_CRON_FIELD_COUNT = 5

# Ranges for each field: (min, max)
_FIELD_RANGES: list[tuple[int, int]] = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 7),  # day of week (0 and 7 = Sunday)
]

_STEP_RE = re.compile(r"^\*/(\d+)$")
_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
_LIST_RE = re.compile(r"^\d+(,\d+)*$")


def _validate_cron_field(value: str, field_min: int, field_max: int) -> bool:
    """Validate a single cron field."""
    if value == "*":
        return True
    # Step: */N
    m = _STEP_RE.match(value)
    if m:
        step = int(m.group(1))
        return 1 <= step <= field_max
    # Range: N-M
    m = _RANGE_RE.match(value)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return field_min <= lo <= field_max and field_min <= hi <= field_max and lo <= hi
    # List: N,M,...
    if _LIST_RE.match(value):
        return all(field_min <= int(v) <= field_max for v in value.split(","))
    # Single number
    if value.isdigit():
        n = int(value)
        return field_min <= n <= field_max
    return False


def validate_cron(expression: str) -> None:
    """Validate a cron expression (5-field format).

    Raises ValueError for invalid expressions or intervals shorter than 15 minutes.
    """
    parts = expression.strip().split()
    if len(parts) != _CRON_FIELD_COUNT:
        msg = f"Invalid cron expression: expected {_CRON_FIELD_COUNT} fields, got {len(parts)}"
        raise ValueError(msg)

    for i, (part, (fmin, fmax)) in enumerate(zip(parts, _FIELD_RANGES, strict=True)):
        if not _validate_cron_field(part, fmin, fmax):
            field_names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
            msg = f"Invalid cron expression: bad {field_names[i]} field '{part}'"
            raise ValueError(msg)

    # Enforce 15-minute minimum interval.
    # If minute field is * and hour field is *, that's every minute — reject.
    # If minute field is */N, N must be >= 15.
    minute_field = parts[0]
    hour_field = parts[1]

    if minute_field == "*" and hour_field == "*":
        msg = "Schedule too frequent: minimum interval is 15 min"
        raise ValueError(msg)

    m = _STEP_RE.match(minute_field)
    if m and hour_field == "*":
        step = int(m.group(1))
        if step < 15:
            msg = "Schedule too frequent: minimum interval is 15 min"
            raise ValueError(msg)


# ── Data types ───────────────────────────────────────────────────────


@dataclass
class ScheduledTask:
    """A user-created recurring task."""

    id: str = ""
    user_id: str = ""
    org_id: str = ""
    name: str = ""
    schedule: str = ""  # cron expression
    prompt: str = ""
    agent: str = ""  # optional, auto-classify if empty
    delivery: str = ""  # channel for results
    enabled: bool = True
    created_at: float = 0.0
    last_run_at: float = 0.0
    run_count: int = 0


@dataclass
class TaskExecution:
    """Record of a single task execution."""

    id: str = ""
    task_id: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = ""  # "success", "error"
    result_preview: str = ""  # first 500 chars


# ── Store ────────────────────────────────────────────────────────────

MAX_TASKS_PER_USER = 10


@dataclass
class InMemoryScheduleStore:
    """In-memory store for scheduled tasks. PostgreSQL version for production."""

    _tasks: dict[str, ScheduledTask] = field(default_factory=dict)
    _executions: dict[str, list[TaskExecution]] = field(default_factory=dict)

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        """Create a scheduled task.

        Validates the cron expression and enforces the per-user maximum.

        Raises:
            ValueError: If cron is invalid, too frequent, or user has hit the limit.
        """
        validate_cron(task.schedule)

        # Enforce per-user limit
        user_count = sum(
            1 for t in self._tasks.values() if t.user_id == task.user_id and t.org_id == task.org_id
        )
        if user_count >= MAX_TASKS_PER_USER:
            msg = f"User has reached the maximum of {MAX_TASKS_PER_USER} scheduled tasks"
            raise ValueError(msg)

        task.id = str(uuid.uuid4())[:8]
        task.created_at = time.time()
        self._tasks[task.id] = task
        return task

    async def get(self, task_id: str, *, org_id: str) -> ScheduledTask | None:
        """Get a task by ID, scoped to org."""
        task = self._tasks.get(task_id)
        if task is None or task.org_id != org_id:
            return None
        return task

    async def list_for_user(self, *, user_id: str, org_id: str) -> list[ScheduledTask]:
        """List all tasks for a user within their org."""
        return [t for t in self._tasks.values() if t.user_id == user_id and t.org_id == org_id]

    async def update(self, task_id: str, *, org_id: str, **fields: Any) -> ScheduledTask | None:
        """Update specific fields on a task. Returns None if not found or wrong org."""
        task = self._tasks.get(task_id)
        if task is None or task.org_id != org_id:
            return None

        # Validate cron if being updated
        if "schedule" in fields:
            validate_cron(fields["schedule"])

        for key, value in fields.items():
            if hasattr(task, key) and key not in ("id", "user_id", "org_id", "created_at"):
                setattr(task, key, value)
        return task

    async def delete(self, task_id: str, *, org_id: str) -> bool:
        """Delete a task. Returns False if not found or wrong org."""
        task = self._tasks.get(task_id)
        if task is None or task.org_id != org_id:
            return False
        del self._tasks[task_id]
        self._executions.pop(task_id, None)
        return True

    async def record_execution(self, task_id: str, execution: TaskExecution) -> None:
        """Record a task execution."""
        if task_id not in self._executions:
            self._executions[task_id] = []
        self._executions[task_id].append(execution)

    async def get_history(
        self, task_id: str, *, org_id: str, limit: int = 10
    ) -> list[TaskExecution]:
        """Get execution history for a task, scoped to org."""
        task = self._tasks.get(task_id)
        if task is None or task.org_id != org_id:
            return []
        executions = self._executions.get(task_id, [])
        # Return most recent first
        return list(reversed(executions))[:limit]

    async def list_enabled(self) -> list[ScheduledTask]:
        """List all enabled tasks across all users (for Reactor evaluation)."""
        return [t for t in self._tasks.values() if t.enabled]
