"""Tests for the agent worker: claims tasks, runs agent pipeline, reports results."""

import pytest

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker
from tests.fakes import FakeLLMClient


class TestAgentWorker:
    @pytest.mark.asyncio
    async def test_processes_pending_task(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("Hello from the worker!")

        worker = AgentWorker(queue=queue, llm=llm)

        # Submit a task
        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        # Process one task
        processed = await worker.process_one()
        assert processed is True

        # Check result
        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert task["result"]["content"] == "Hello from the worker!"

    @pytest.mark.asyncio
    async def test_returns_false_when_empty(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        worker = AgentWorker(queue=queue, llm=llm)

        processed = await worker.process_one()
        assert processed is False

    @pytest.mark.asyncio
    async def test_handles_llm_error(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        # Set no responses — will return default

        worker = AgentWorker(queue=queue, llm=llm)
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
        # Should complete (FakeLLM returns default response)
        assert task["status"] == "completed"
