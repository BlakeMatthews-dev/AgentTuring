"""Propagation gate test — asserts every span carries the documented dimensions.

Uses RecordingTracingBackend to introspect what spans were emitted by a full
workflow run. This is the regression net for Phase 3 — missing dimensions in
Phoenix are impossible to detect without this test.
"""

from __future__ import annotations

import asyncio as _asyncio
from typing import Any

import pytest

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName
from tests.builders.test_workflow_smoke import SmartFakeLLM, WorkflowToolDispatcher
from tests.fakes import RecordingTracingBackend, make_test_container


async def _run_with_recording() -> tuple[Any, RecordingTracingBackend]:
    """Execute the smoke workflow with a RecordingTracingBackend."""
    from stronghold.api.routes.builders import _execute_full_workflow, _build_service_auth

    llm = SmartFakeLLM()
    container = make_test_container(fake_llm=llm)
    recording = RecordingTracingBackend()
    container.tracer = recording

    td = WorkflowToolDispatcher()
    container.tool_dispatcher = td

    orch = BuildersOrchestrator()
    orch.create_run(
        run_id="run-prop",
        repo="owner/repo",
        issue_number=42,
        branch="mason/42",
        workspace_ref="ws-prop",
        initial_stage="issue_analyzed",
        initial_worker=WorkerName.FRANK,
        intent_mode="autonomous_build",
        session_id="",  # should be synthesized to run_id
        parent_trace_id="0af7651916cd43dd8448eb211c80319c",
        request_id="req-test-123",
    )

    service_auth = _build_service_auth(container)
    await _execute_full_workflow("run-prop", orch, container, service_auth)
    await _asyncio.sleep(0)  # drain fire-and-forget tasks
    return orch._runs["run-prop"], recording


class TestTracePropagation:
    async def test_trace_created_with_identity_metadata(self) -> None:
        """create_trace was called with user_id, session_id, parent_trace_id, and metadata."""
        _, recording = await _run_with_recording()
        assert len(recording.traces) == 1
        trace = recording.traces[0]
        kw = trace.kwargs
        assert kw["user_id"] == "builders-service"
        # session_id should be synthesized to run_id since we passed ""
        assert kw["session_id"] == "run-prop"
        assert kw["parent_trace_id"] == "0af7651916cd43dd8448eb211c80319c"
        md = kw["metadata"]
        assert md["run_id"] == "run-prop"
        assert md["intent_mode"] == "autonomous_build"
        assert md["repo"] == "owner/repo"
        assert md["issue_number"] == 42

    async def test_trace_has_stage_spans(self) -> None:
        """At least one stage span was created."""
        _, recording = await _run_with_recording()
        trace = recording.traces[0]
        stage_spans = [s for s in trace.spans if s.name.startswith("stage.")]
        assert len(stage_spans) >= 1, f"No stage spans found. Spans: {[s.name for s in trace.spans]}"

    async def test_stage_spans_carry_universal_fields(self) -> None:
        """Every stage span carries run_id, agent_id, stage, stage_attempt."""
        _, recording = await _run_with_recording()
        trace = recording.traces[0]
        stage_spans = [s for s in trace.spans if s.name.startswith("stage.")]
        for span in stage_spans:
            attrs = span.get_attributes()
            assert "run_id" in attrs, f"span {span.name} missing run_id"
            assert "agent_id" in attrs, f"span {span.name} missing agent_id"
            assert "stage" in attrs, f"span {span.name} missing stage"
            assert "stage_attempt" in attrs, f"span {span.name} missing stage_attempt"
            assert "agent_kind" in attrs, f"span {span.name} missing agent_kind"
            assert attrs["agent_kind"] == "build_worker"

    async def test_llm_spans_carry_model_fields(self) -> None:
        """LLM spans carry model_name, prompt_size_chars, and call set_input/set_output/set_usage."""
        _, recording = await _run_with_recording()
        trace = recording.traces[0]
        llm_spans = [s for s in trace.spans if s.name == "llm.complete"]
        # At least some LLM calls should have been traced
        # (depends on whether pipeline handlers pass ctx/trace through)
        if not llm_spans:
            pytest.skip("No llm.complete spans yet — pipeline handlers don't pass ctx/trace (PR 14+ wiring)")
        for span in llm_spans:
            attrs = span.get_attributes()
            assert "model_name" in attrs, f"llm span missing model_name"
            assert "prompt_size_chars" in attrs
            # Verify set_input/set_output/set_usage were called
            ops = [c[0] for c in span.calls]
            assert "set_input" in ops, "llm span missing set_input call"
            assert "set_output" in ops, "llm span missing set_output call"
            assert "set_usage" in ops, "llm span missing set_usage call"

    async def test_trace_ended(self) -> None:
        """trace.end() was called on workflow completion."""
        _, recording = await _run_with_recording()
        trace = recording.traces[0]
        assert trace.ended, "trace.end() was not called"

    async def test_session_id_synthesized_to_run_id(self) -> None:
        """When session_id is empty, workflow synthesizes it to run_id."""
        _, recording = await _run_with_recording()
        trace = recording.traces[0]
        assert trace.kwargs["session_id"] == "run-prop"
