from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runtime_has_no_durable_run_registry() -> None:
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
    result = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )

    # The handler result is returned as expected.
    assert result.status is RunStatus.PASSED
    assert result.run_id == "run-1"

    # Behavioral proof of statelessness: no _runs map in runtime state; the
    # only persisted state is the handler registry keyed by worker.
    assert "_runs" not in runtime.__dict__
    assert sorted(runtime._handlers.keys()) == [WorkerName.FRANK]

    # Re-executing the same run_id must not raise "already seen" — a stateless
    # runtime cannot remember the previous execution.
    second = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )
    assert second.status is RunStatus.PASSED
