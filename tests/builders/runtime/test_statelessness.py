from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runtime_does_not_mutate_request_or_store_run_state() -> None:
    runtime = BuildersRuntime()

    async def handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="ok",
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", handler)

    request = RunRequest(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="acceptance_defined",
        repo="org/repo",
        issue_number=42,
        branch="b",
        workspace_ref="ws",
        context={"attempt": 1},
    )

    result_one = await runtime.execute(request)
    result_two = await runtime.execute(request)

    # Both executions return independent, identical-valued RunResult objects.
    assert result_one.summary == "ok"
    assert result_two.summary == "ok"
    assert result_one.run_id == result_two.run_id
    assert result_one.status is RunStatus.PASSED

    # Behavioral: the input request is not mutated by execute().
    assert request.context == {"attempt": 1}

    # Behavioral: the runtime has no user-visible attribute for persisted runs.
    # We check via the public/state surface: listing dir() should NOT expose
    # anything that looks like a run registry.
    public_state = {name for name in dir(runtime) if "run" in name.lower() and not name.startswith("_")}
    assert public_state == set(), f"Runtime leaks run state via public API: {public_state}"
    # And privately, there is no _runs map to accrete state in.
    assert "_runs" not in runtime.__dict__
