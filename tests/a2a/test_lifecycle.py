"""Tests for A2A TaskQueue, WorkerPool, TaskLifecycle.

Spec: Priority-based task queue, bounded worker pool, unified lifecycle manager.
AC: enqueue returns id, dequeue respects priority (P0>P5), worker pool enforces
    max_workers, lifecycle creates and tracks tasks.
Edge cases: empty queue dequeue, unknown priority, pool at capacity, queue size counts.
Contracts: enqueue returns str id, dequeue returns dict|None, size returns int.
"""

from __future__ import annotations

import asyncio

import pytest

from stronghold.a2a.lifecycle import (
    TaskLifecycle,
    TaskQueue,
    WorkerConfig,
    WorkerPool,
)


class TestTaskQueue:
    def test_enqueue_returns_id(self) -> None:
        q = TaskQueue()
        tid = asyncio.run(q.enqueue({"task": "a"}))
        assert isinstance(tid, str)

    def test_dequeue_highest_priority_first(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            await q.enqueue({"name": "low"}, priority="P4")
            await q.enqueue({"name": "high"}, priority="P0")
            await q.enqueue({"name": "mid"}, priority="P2")
            task = await q.dequeue()
            assert task is not None
            assert task["name"] == "high"
            task = await q.dequeue()
            assert task is not None
            assert task["name"] == "mid"

        asyncio.run(_test())

    def test_dequeue_specific_priority(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            await q.enqueue({"name": "a"}, priority="P0")
            await q.enqueue({"name": "b"}, priority="P3")
            task = await q.dequeue(priority="P3")
            assert task is not None
            assert task["name"] == "b"

        asyncio.run(_test())

    def test_dequeue_empty_returns_none(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            assert await q.dequeue() is None

        asyncio.run(_test())

    def test_size_counts_all_priorities(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            await q.enqueue({"a": 1}, priority="P0")
            await q.enqueue({"b": 2}, priority="P3")
            assert q.size() == 2

        asyncio.run(_test())

    def test_size_by_priority(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            await q.enqueue({"a": 1}, priority="P0")
            await q.enqueue({"b": 2}, priority="P0")
            assert q.size_by_priority("P0") == 2
            assert q.size_by_priority("P3") == 0

        asyncio.run(_test())

    def test_dequeue_removes_item(self) -> None:
        async def _test() -> None:
            q = TaskQueue()
            await q.enqueue({"x": 1})
            await q.dequeue()
            assert q.size() == 0

        asyncio.run(_test())


class TestWorkerPool:
    def test_submit_within_capacity(self) -> None:
        async def _test() -> None:
            pool = WorkerPool(WorkerConfig(max_workers=2))
            await pool.submit("t1", {"data": "a"})
            assert "t1" in pool.get_active_tasks()

        asyncio.run(_test())

    def test_submit_exceeds_capacity_raises(self) -> None:
        async def _test() -> None:
            pool = WorkerPool(WorkerConfig(max_workers=1))
            await pool.submit("t1", {"data": "a"})
            with pytest.raises(RuntimeError, match="capacity"):
                await pool.submit("t2", {"data": "b"})

        asyncio.run(_test())

    def test_get_status(self) -> None:
        async def _test() -> None:
            pool = WorkerPool(WorkerConfig(max_workers=4))
            status = pool.get_status()
            assert "active_tasks" in status
            assert "max_workers" in status

        asyncio.run(_test())


class TestTaskLifecycle:
    def test_create_and_get(self) -> None:
        async def _test() -> None:
            lc = TaskLifecycle()
            tid = await lc.create_task({"action": "build"})
            status = await lc.get_task_status(tid)
            assert status is not None
            assert "task_id" in status

        asyncio.run(_test())

    def test_get_queue_status(self) -> None:
        async def _test() -> None:
            lc = TaskLifecycle()
            qs = await lc.get_queue_status()
            assert isinstance(qs, dict)

        asyncio.run(_test())
