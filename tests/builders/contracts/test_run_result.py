from __future__ import annotations

from stronghold.builders import RunResult, RunStatus, WorkerName


def test_run_result_optional_lists_default_isolated() -> None:
    """Two RunResult instances must have independent claims/logs lists.

    A classic dataclass bug is passing a shared mutable default (= [])
    instead of a factory. Construct two results and mutate one — the other
    must remain empty.
    """
    r1 = RunResult(
        run_id="run-1",
        worker=WorkerName.MASON,
        stage="implementation_started",
        status=RunStatus.PASSED,
        summary="r1",
    )
    r2 = RunResult(
        run_id="run-2",
        worker=WorkerName.MASON,
        stage="implementation_started",
        status=RunStatus.PASSED,
        summary="r2",
    )

    r1.claims.append("claim-1")
    r1.logs.append("log-1")

    # If factory defaults were swapped for a shared list, r2 would now
    # contain r1's entries.
    assert r2.claims == []
    assert r2.logs == []
