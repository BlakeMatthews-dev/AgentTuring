"""Tests that the workflow emits StageEvents at documented decision points.

Uses the same SmartFakeLLM + WorkflowToolDispatcher from test_workflow_smoke
but asserts on the specific event types emitted to run.events.
"""

from __future__ import annotations

import json
from typing import Any

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName
from tests.builders.test_workflow_smoke import SmartFakeLLM, WorkflowToolDispatcher
from tests.fakes import make_test_container


async def _run_workflow() -> Any:
    """Execute the smoke workflow and return the run object."""
    import asyncio as _asyncio

    from stronghold.api.routes.builders import _execute_full_workflow, _build_service_auth

    llm = SmartFakeLLM()
    container = make_test_container(fake_llm=llm)
    td = WorkflowToolDispatcher()
    container.tool_dispatcher = td

    orch = BuildersOrchestrator()
    orch.create_run(
        run_id="run-events",
        repo="owner/repo",
        issue_number=42,
        branch="mason/42",
        workspace_ref="ws-events",
        initial_stage="issue_analyzed",
        initial_worker=WorkerName.FRANK,
    )

    service_auth = _build_service_auth(container)
    await _execute_full_workflow("run-events", orch, container, service_auth)
    await _asyncio.sleep(0)  # drain fire-and-forget tasks
    return orch._runs["run-events"]


class TestStageEvents:
    async def test_run_created_event_exists(self) -> None:
        run = await _run_workflow()
        event_types = [e.event for e in run.events]
        assert "run_created" in event_types

    async def test_stage_attempt_started_events(self) -> None:
        run = await _run_workflow()
        started = [e for e in run.events if e.event == "stage_attempt_started"]
        assert len(started) >= 1, f"Expected >=1 stage_attempt_started, got {len(started)}"

    async def test_stage_attempt_completed_events(self) -> None:
        run = await _run_workflow()
        completed = [e for e in run.events if e.event == "stage_attempt_completed"]
        assert len(completed) >= 1, f"Expected >=1 stage_attempt_completed, got {len(completed)}"

    async def test_auditor_verdict_events(self) -> None:
        run = await _run_workflow()
        verdicts = [e for e in run.events if e.event == "auditor_verdict"]
        assert len(verdicts) >= 1, f"Expected >=1 auditor_verdict, got {len(verdicts)}"

    async def test_outer_loop_started_event(self) -> None:
        run = await _run_workflow()
        outer = [e for e in run.events if e.event == "outer_loop_started"]
        assert len(outer) >= 1, f"Expected >=1 outer_loop_started, got {len(outer)}"

    async def test_event_count_at_least_10(self) -> None:
        """A full workflow should produce a rich audit trail."""
        run = await _run_workflow()
        assert len(run.events) >= 10, (
            f"Expected >=10 events, got {len(run.events)}: "
            f"{[e.event for e in run.events]}"
        )

    async def test_events_have_run_id(self) -> None:
        run = await _run_workflow()
        for e in run.events:
            assert e.run_id == "run-events", f"Event {e.event} has wrong run_id: {e.run_id}"

    async def test_events_have_timestamps(self) -> None:
        run = await _run_workflow()
        for e in run.events:
            assert e.timestamp is not None, f"Event {e.event} missing timestamp"
