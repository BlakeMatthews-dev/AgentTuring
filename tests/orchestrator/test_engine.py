"""Tests for the Orchestrator execution engine."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from stronghold.orchestrator.engine import OrchestratorEngine, WorkItem, WorkStatus


class FakeAgentResponse:
    def __init__(self, content: str = "done") -> None:
        self.content = content
        self.tool_history: list[dict[str, Any]] = []


class FakeAgent:
    """Fake agent that records handle() calls."""

    def __init__(self, response: str = "done", fail: bool = False) -> None:
        self._response = response
        self._fail = fail
        self.calls: list[dict[str, Any]] = []

    async def handle(
        self,
        messages: list[dict[str, Any]],
        auth: Any,
        **kwargs: Any,
    ) -> FakeAgentResponse:
        self.calls.append({"messages": messages})
        if self._fail:
            raise RuntimeError("agent execution failed")
        return FakeAgentResponse(self._response)


class FakeContainer:
    """Minimal container stub for orchestrator tests."""

    def __init__(self, response: str = "done", fail: bool = False) -> None:
        self._response = response
        self._fail = fail
        mason = FakeAgent(response, fail)
        auditor = FakeAgent(response, fail)
        ranger = FakeAgent(response, fail)
        self.agents: dict[str, FakeAgent] = {"mason": mason, "auditor": auditor, "ranger": ranger}
        self.reactor = FakeReactor()

    @property
    def calls(self) -> list[dict[str, Any]]:
        all_calls: list[dict[str, Any]] = []
        for agent in self.agents.values():
            all_calls.extend(agent.calls)
        return all_calls


class FakeReactor:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)


class TestDispatch:
    def test_dispatch_creates_work_item(self) -> None:
        engine = OrchestratorEngine(FakeContainer())
        item = engine.dispatch(
            work_id="test-1",
            agent_name="mason",
            messages=[{"role": "user", "content": "implement #42"}],
            trigger="api",
            priority_tier="P5",
        )
        assert item.id == "test-1"
        assert item.agent_name == "mason"
        assert item.status == WorkStatus.QUEUED
        assert item.trigger == "api"
        assert item.priority_tier == "P5"

    def test_dispatch_metadata(self) -> None:
        engine = OrchestratorEngine(FakeContainer())
        item = engine.dispatch(
            work_id="gh-42",
            agent_name="mason",
            messages=[{"role": "user", "content": "fix it"}],
            metadata={"issue_number": 42, "repo": "stronghold"},
        )
        assert item.metadata["issue_number"] == 42

    def test_list_items(self) -> None:
        engine = OrchestratorEngine(FakeContainer())
        engine.dispatch(work_id="a", agent_name="mason", messages=[{"role": "user", "content": "a"}])
        engine.dispatch(work_id="b", agent_name="auditor", messages=[{"role": "user", "content": "b"}])
        items = engine.list_items()
        assert len(items) == 2

    def test_cancel_queued(self) -> None:
        engine = OrchestratorEngine(FakeContainer())
        engine.dispatch(work_id="c", agent_name="mason", messages=[{"role": "user", "content": "c"}])
        assert engine.cancel("c") is True
        assert engine.get("c").status == WorkStatus.CANCELLED

    def test_status(self) -> None:
        engine = OrchestratorEngine(FakeContainer())
        engine.dispatch(work_id="d", agent_name="mason", messages=[{"role": "user", "content": "d"}])
        s = engine.status()
        assert s["total"] == 1
        assert s["queued"] == 1


class TestExecution:
    async def test_worker_executes_and_completes(self) -> None:
        container = FakeContainer(response="PR created")
        engine = OrchestratorEngine(container, max_concurrent=1)
        await engine.start()

        engine.dispatch(
            work_id="exec-1",
            agent_name="mason",
            messages=[{"role": "user", "content": "implement #42"}],
            intent_hint="code_gen",
        )

        for _ in range(50):
            item = engine.get("exec-1")
            if item and item.status in (WorkStatus.COMPLETED, WorkStatus.FAILED):
                break
            await asyncio.sleep(0.05)

        await engine.stop()

        item = engine.get("exec-1")
        assert item is not None
        assert item.status == WorkStatus.COMPLETED
        assert item.result["choices"][0]["message"]["content"] == "PR created"
        assert item.result["agent"] == "mason"
        assert len(container.calls) == 1

    async def test_worker_handles_failure(self) -> None:
        container = FakeContainer(fail=True)
        engine = OrchestratorEngine(container, max_concurrent=1)
        await engine.start()

        engine.dispatch(
            work_id="fail-1",
            agent_name="mason",
            messages=[{"role": "user", "content": "this will fail"}],
        )

        for _ in range(50):
            item = engine.get("fail-1")
            if item and item.status in (WorkStatus.COMPLETED, WorkStatus.FAILED):
                break
            await asyncio.sleep(0.05)

        await engine.stop()

        item = engine.get("fail-1")
        assert item is not None
        assert item.status == WorkStatus.FAILED
        assert "agent execution failed" in item.error

    async def test_priority_ordering(self) -> None:
        container = FakeContainer()
        engine = OrchestratorEngine(container, max_concurrent=1)
        # Don't start workers yet — queue items first
        engine.dispatch(
            work_id="low", agent_name="mason",
            messages=[{"role": "user", "content": "low"}],
            priority_tier="P5",
        )
        engine.dispatch(
            work_id="high", agent_name="mason",
            messages=[{"role": "user", "content": "high"}],
            priority_tier="P0",
        )

        await engine.start()

        for _ in range(50):
            high = engine.get("high")
            if high and high.status == WorkStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)

        await engine.stop()

        # High priority should have been picked up first
        assert container.calls[0]["messages"][0]["content"] == "high"

    async def test_cancelled_item_skipped(self) -> None:
        container = FakeContainer()
        engine = OrchestratorEngine(container, max_concurrent=1)
        engine.dispatch(
            work_id="cancel-me", agent_name="mason",
            messages=[{"role": "user", "content": "nope"}],
        )
        engine.cancel("cancel-me")
        await engine.start()
        await asyncio.sleep(0.2)
        await engine.stop()
        assert len(container.calls) == 0

    async def test_emits_completion_event(self) -> None:
        container = FakeContainer()
        engine = OrchestratorEngine(container, max_concurrent=1)
        await engine.start()
        engine.dispatch(
            work_id="evt-1", agent_name="mason",
            messages=[{"role": "user", "content": "go"}],
        )
        for _ in range(50):
            item = engine.get("evt-1")
            if item and item.status == WorkStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        await engine.stop()
        assert len(container.reactor.events) >= 1
        assert container.reactor.events[0].name == "mason.work_complete"
