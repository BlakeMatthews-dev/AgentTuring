"""Tests for the task queue: API submits, Worker picks up."""

import pytest

from stronghold.agents.task_queue import InMemoryTaskQueue


class TestTaskQueue:
    @pytest.mark.asyncio
    async def test_submit_and_claim(self) -> None:
        q = InMemoryTaskQueue()
        task_id = await q.submit(
            {"messages": [{"role": "user", "content": "hello"}], "intent": "chat"}
        )
        assert task_id

        task = await q.claim()
        assert task is not None
        assert task["id"] == task_id
        assert task["status"] == "working"

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_empty(self) -> None:
        q = InMemoryTaskQueue()
        task = await q.claim()
        assert task is None

    @pytest.mark.asyncio
    async def test_complete_task(self) -> None:
        q = InMemoryTaskQueue()
        task_id = await q.submit({"messages": []})
        await q.claim()
        await q.complete(task_id, {"content": "done"})

        task = await q.get(task_id)
        assert task["status"] == "completed"
        assert task["result"]["content"] == "done"

    @pytest.mark.asyncio
    async def test_fail_task(self) -> None:
        q = InMemoryTaskQueue()
        task_id = await q.submit({"messages": []})
        await q.claim()
        await q.fail(task_id, "something broke")

        task = await q.get(task_id)
        assert task["status"] == "failed"
        assert task["error"] == "something broke"

    @pytest.mark.asyncio
    async def test_get_status(self) -> None:
        q = InMemoryTaskQueue()
        task_id = await q.submit({"messages": []})
        task = await q.get(task_id)
        assert task["status"] == "pending"

    @pytest.mark.asyncio
    async def test_multiple_tasks_fifo(self) -> None:
        q = InMemoryTaskQueue()
        id1 = await q.submit({"messages": [{"role": "user", "content": "first"}]})
        id2 = await q.submit({"messages": [{"role": "user", "content": "second"}]})

        task1 = await q.claim()
        assert task1 is not None
        assert task1["id"] == id1

        task2 = await q.claim()
        assert task2 is not None
        assert task2["id"] == id2
