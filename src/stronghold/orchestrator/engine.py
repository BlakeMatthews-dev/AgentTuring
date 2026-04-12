"""Orchestrator execution engine.

The engine is the core loop that:
1. Accepts work items (agent + task + trigger source)
2. Queues them with priority (using the 6-tier system)
3. Executes them through the Conduit pipeline with full governance
4. Tracks state transitions (queued -> running -> done/failed)
5. Emits events for downstream reactors (RLHF, audit, notifications)

Any agent can be dispatched: Mason, Auditor, Ranger, or custom.
Any trigger can fire: GitHub webhook, cron, API call, reactor event.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger("stronghold.orchestrator.engine")


class WorkStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkItem:
    """A unit of work dispatched to an agent."""

    id: str
    agent_name: str
    messages: list[dict[str, Any]]
    trigger: str  # "api", "webhook", "cron", "reactor", "manual"
    priority_tier: str = "P2"
    intent_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: WorkStatus = WorkStatus.QUEUED
    result: dict[str, Any] | None = None
    error: str = ""
    log: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "trigger": self.trigger,
            "priority_tier": self.priority_tier,
            "status": self.status.value,
            "error": self.error,
            "log_lines": len(self.log),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }


# Priority values — lower number = higher priority = runs first
_TIER_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}


class OrchestratorEngine:
    """Agent execution engine.

    Submit work items via dispatch(). The engine runs them through the
    Conduit pipeline (container.route_request) with governance, tracking,
    and event emission. Work items are priority-ordered by tier.
    """

    def __init__(
        self,
        container: Any,
        *,
        max_concurrent: int = 3,
    ) -> None:
        self._container = container
        self._max_concurrent = max_concurrent
        # Expose a stable read-only check — pipeline should use this,
        # not reach through to _container.agents directly.
        self.has_agent = lambda name: name in container.agents
        self._items: dict[str, WorkItem] = {}
        self._queue: asyncio.PriorityQueue[tuple[int, str]] = asyncio.PriorityQueue()
        self._running: set[str] = set()
        self._workers: list[asyncio.Task[None]] = []
        self._shutdown = False

    async def start(self) -> None:
        """Start worker tasks."""
        logger.info(
            "Orchestrator started: max_concurrent=%d",
            self._max_concurrent,
        )
        for i in range(self._max_concurrent):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)

    async def stop(self) -> None:
        """Stop all workers gracefully."""
        self._shutdown = True
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        logger.info("Orchestrator stopped")

    def dispatch(
        self,
        *,
        work_id: str,
        agent_name: str,
        messages: list[dict[str, Any]],
        trigger: str = "api",
        priority_tier: str = "P2",
        intent_hint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkItem:
        """Submit a work item for execution. Returns immediately."""
        item = WorkItem(
            id=work_id,
            agent_name=agent_name,
            messages=messages,
            trigger=trigger,
            priority_tier=priority_tier,
            intent_hint=intent_hint,
            metadata=metadata or {},
        )
        self._items[work_id] = item
        priority = _TIER_PRIORITY.get(priority_tier, 2)
        self._queue.put_nowait((priority, work_id))
        logger.info(
            "Work dispatched: id=%s agent=%s trigger=%s tier=%s",
            work_id,
            agent_name,
            trigger,
            priority_tier,
        )
        return item

    def get(self, work_id: str) -> WorkItem | None:
        return self._items.get(work_id)

    def list_items(self, status: WorkStatus | None = None) -> list[dict[str, object]]:
        all_items = list(self._items.values())
        if status:
            all_items = [i for i in all_items if i.status == status]
        return [i.to_dict() for i in all_items]

    def cancel(self, work_id: str) -> bool:
        item = self._items.get(work_id)
        if item and item.status == WorkStatus.QUEUED:
            item.status = WorkStatus.CANCELLED
            return True
        return False

    def status(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for i in self._items.values():
            counts[i.status.value] = counts.get(i.status.value, 0) + 1
        return {
            "total": len(self._items),
            "running": len(self._running),
            "max_concurrent": self._max_concurrent,
            **counts,
        }

    async def _worker(self, worker_id: int) -> None:
        """Worker loop — dequeue and execute work items."""
        while not self._shutdown:
            try:
                priority, work_id = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
            except TimeoutError:
                continue

            item = self._items.get(work_id)
            if item is None or item.status == WorkStatus.CANCELLED:
                continue

            self._running.add(work_id)
            item.status = WorkStatus.RUNNING
            item.started_at = datetime.now(UTC)
            item.log.append(f"Worker {worker_id} picked up work")

            logger.info(
                "Worker %d executing: id=%s agent=%s",
                worker_id,
                work_id,
                item.agent_name,
            )

            try:
                result = await self._execute(item)
                item.status = WorkStatus.COMPLETED
                item.result = result
                item.completed_at = datetime.now(UTC)
                item.log.append("Completed successfully")

                # Emit completion event for downstream reactors
                self._emit_event(
                    f"{item.agent_name}.work_complete",
                    {"work_id": work_id, "agent": item.agent_name},
                )
                logger.info("Work completed: id=%s agent=%s", work_id, item.agent_name)

            except Exception as exc:
                item.status = WorkStatus.FAILED
                item.error = str(exc)
                item.completed_at = datetime.now(UTC)
                item.log.append(f"Failed: {exc}")
                item.log.append(traceback.format_exc())

                self._emit_event(
                    f"{item.agent_name}.work_failed",
                    {"work_id": work_id, "agent": item.agent_name, "error": str(exc)},
                )
                logger.error(
                    "Work failed: id=%s agent=%s error=%s",
                    work_id,
                    item.agent_name,
                    exc,
                )

            finally:
                self._running.discard(work_id)

    async def _execute(self, item: WorkItem) -> dict[str, Any]:
        """Execute a work item by calling the agent directly.

        Skips classification (we already know the agent). Goes straight to
        Agent.handle() which runs the full pipeline:
        Warden scan -> context build -> strategy.reason() (tool loop) ->
        Sentinel post-call -> learning extraction -> response
        """
        from stronghold.types.auth import SYSTEM_AUTH  # noqa: PLC0415

        agent = self._container.agents.get(item.agent_name)
        if agent is None:
            msg = f"Agent '{item.agent_name}' not loaded"
            raise LookupError(msg)

        response = await agent.handle(
            item.messages,
            SYSTEM_AUTH,
        )
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": response.content,
                    },
                }
            ],
            "agent": item.agent_name,
            "tool_history": [
                {"tool": t["tool_name"], "round": t["round"]}
                for t in getattr(response, "tool_history", [])
            ],
        }

    def _emit_event(self, name: str, data: dict[str, Any]) -> None:
        """Emit an event to the reactor for downstream processing."""
        try:
            from stronghold.types.reactor import Event  # noqa: PLC0415

            event = Event(name=name, data=data)
            self._container.reactor.emit(event)
        except Exception:
            logger.debug("Event emission failed (reactor may not be running)", exc_info=True)
