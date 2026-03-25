"""Agent Worker: claims tasks from the queue and runs agent pipelines.

Runs in its own pod/process. Picks up tasks, runs the agent,
reports results back to the queue.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.agents.task_queue import InMemoryTaskQueue
    from stronghold.protocols.llm import LLMClient

logger = logging.getLogger("stronghold.worker")


class AgentWorker:
    """Claims tasks from the queue and processes them via agents."""

    def __init__(
        self,
        queue: InMemoryTaskQueue,
        llm: LLMClient,
    ) -> None:
        self._queue = queue
        self._llm = llm

    async def process_one(self) -> bool:
        """Claim and process one task. Returns True if a task was processed."""
        task = await self._queue.claim()
        if task is None:
            return False

        task_id = task["id"]
        payload = task.get("payload", {})

        try:
            result = await self._run_agent(payload)
            await self._queue.complete(task_id, result)
        except Exception as exc:
            logger.exception("Task %s failed", task_id)
            await self._queue.fail(task_id, str(exc))

        return True

    async def _run_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the agent pipeline for a task payload."""
        messages = payload.get("messages", [])
        model = payload.get("model", "auto")

        # Call LLM directly for now — full agent pipeline integration later
        response = await self._llm.complete(messages, model)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        return {
            "content": content,
            "agent": payload.get("agent", "default"),
            "model": model,
        }

    async def run_loop(self, max_idle_seconds: float = 5.0) -> None:
        """Run the worker loop: claim → process → repeat.

        Stops after max_idle_seconds with no tasks.
        """
        import asyncio

        idle_time = 0.0
        poll_interval = 0.5

        while idle_time < max_idle_seconds:
            processed = await self.process_one()
            if processed:
                idle_time = 0.0
            else:
                await asyncio.sleep(poll_interval)
                idle_time += poll_interval
