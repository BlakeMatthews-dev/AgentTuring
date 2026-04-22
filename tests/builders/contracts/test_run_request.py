from __future__ import annotations

from pydantic import ValidationError

from stronghold.builders import RunRequest, WorkerName


def test_run_request_rejects_missing_required_fields() -> None:
    try:
        RunRequest(  # type: ignore[call-arg]
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            repo="org/repo",
            branch="builders/42-run-1",
            workspace_ref="ws-1",
        )
    except ValidationError as exc:
        assert "issue_number" in str(exc)
    else:
        raise AssertionError("ValidationError expected")
