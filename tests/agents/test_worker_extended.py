"""Extended tests for agent worker: failure handling, run_loop idle timeout."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker
from tests.fakes import FakeLLMClient


class FailingLLMClient:
    """LLM client that always raises an exception on complete()."""

    def __init__(self, error_message: str = "LLM service unavailable") -> None:
        self._error_message = error_message
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "model": model})
        raise RuntimeError(self._error_message)


class TestWorkerProcessOneNoTasks:
    async def test_no_tasks_returns_false(self) -> None:
        """process_one with empty queue returns False."""
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        worker = AgentWorker(queue=queue, llm=llm)

        result = await worker.process_one()
        assert result is False


class TestWorkerProcessOneSuccess:
    async def test_task_available_processes_and_completes(self) -> None:
        """process_one claims a task, runs the LLM, and marks it completed."""
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("worker output here")

        worker = AgentWorker(queue=queue, llm=llm)

        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "do something"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        processed = await worker.process_one()
        assert processed is True

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert task["result"]["content"] == "worker output here"
        assert task["result"]["agent"] == "arbiter"
        assert task["result"]["model"] == "test/model"


class TestWorkerProcessOneLLMFailure:
    async def test_llm_failure_marks_task_as_failed(self) -> None:
        """When the LLM raises, the task is marked as failed with the error."""
        queue = InMemoryTaskQueue()
        failing_llm = FailingLLMClient("connection refused")
        worker = AgentWorker(queue=queue, llm=failing_llm)

        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        processed = await worker.process_one()
        assert processed is True

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "failed"
        assert "connection refused" in task["error"]


class TestWorkerRunLoop:
    async def test_run_loop_processes_tasks_then_idles_out(self) -> None:
        """run_loop processes all available tasks then exits after idle timeout."""
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("looped response")

        worker = AgentWorker(queue=queue, llm=llm)

        # Submit 3 tasks
        ids = []
        for i in range(3):
            task_id = await queue.submit(
                {
                    "messages": [{"role": "user", "content": f"task {i}"}],
                    "agent": "arbiter",
                    "model": "test/model",
                }
            )
            ids.append(task_id)

        # Run with short idle timeout so it exits quickly after tasks are done
        await worker.run_loop(max_idle_seconds=1.0)

        # All 3 tasks should be completed
        for task_id in ids:
            task = await queue.get(task_id)
            assert task is not None
            assert task["status"] == "completed"

    async def test_run_loop_exits_on_idle_with_no_tasks(self) -> None:
        """run_loop exits quickly when there are no tasks at all."""
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        worker = AgentWorker(queue=queue, llm=llm)

        # Should return without error after idle timeout
        await worker.run_loop(max_idle_seconds=1.0)
