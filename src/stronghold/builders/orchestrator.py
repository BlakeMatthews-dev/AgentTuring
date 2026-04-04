"""Builders 2.0 orchestrator skeleton.

Stronghold core owns workflow state. Builders runtime only returns results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from stronghold.builders.contracts import (
        ArtifactRef,
        RunRequest,
        RunResult,
    )

from stronghold.builders.contracts import RunRequest, RunStatus, StageEvent, WorkerName

_ALLOWED_STAGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("issue_analyzed",),
    "issue_analyzed": ("acceptance_defined", "blocked"),
    "acceptance_defined": ("tests_written", "blocked"),
    "tests_written": ("implementation_started", "blocked"),
    "implementation_started": ("implementation_ready", "blocked", "failed"),
    "implementation_ready": (
        "quality_checks_passed",
        "implementation_started",
        "acceptance_defined",
        "failed",
    ),
    "quality_checks_passed": ("completed", "acceptance_defined", "failed"),
    "blocked": (),
    "failed": (),
    "completed": (),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunState:
    """Minimal in-memory run record."""

    run_id: str
    repo: str
    issue_number: int
    branch: str
    workspace_ref: str
    current_stage: str
    current_worker: WorkerName
    runtime_version: str = "v1"
    status: RunStatus = RunStatus.QUEUED
    artifacts: list[ArtifactRef] = field(default_factory=list)
    events: list[StageEvent] = field(default_factory=list)
    retries: dict[str, int] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass
class RuntimeVersionState:
    """Lifecycle state for a Builders runtime version."""

    version: str
    state: str = "ready"  # ready | draining | retired


class BuildersOrchestrator:
    """Minimal orchestration state holder for Builders 2.0."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._runtime_versions: dict[str, RuntimeVersionState] = {
            "v1": RuntimeVersionState(version="v1", state="ready")
        }

    def register_runtime_version(
        self, version: str, *, state: str = "ready"
    ) -> RuntimeVersionState:
        runtime = RuntimeVersionState(version=version, state=state)
        self._runtime_versions[version] = runtime
        return runtime

    def set_runtime_state(self, version: str, state: str) -> RuntimeVersionState:
        runtime = self._runtime_versions[version]
        runtime.state = state
        return runtime

    def select_runtime_version(self) -> str:
        ready_versions = sorted(
            [
                runtime.version
                for runtime in self._runtime_versions.values()
                if runtime.state == "ready"
            ]
        )
        if not ready_versions:
            raise ValueError("no ready runtime version available")
        return ready_versions[-1]

    def active_runs_for_version(self, version: str) -> int:
        return sum(
            1
            for run in self._runs.values()
            if run.runtime_version == version
            and run.status not in {RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED}
        )

    def create_run(
        self,
        *,
        run_id: str,
        repo: str,
        issue_number: int,
        branch: str,
        workspace_ref: str,
        initial_stage: str = "queued",
        initial_worker: WorkerName = WorkerName.FRANK,
        runtime_version: str | None = None,
    ) -> RunState:
        assigned_runtime_version = runtime_version or self.select_runtime_version()
        run = RunState(
            run_id=run_id,
            repo=repo,
            issue_number=issue_number,
            branch=branch,
            workspace_ref=workspace_ref,
            current_stage=initial_stage,
            current_worker=initial_worker,
            runtime_version=assigned_runtime_version,
        )
        run.events.append(
            StageEvent(
                run_id=run_id,
                stage=initial_stage,
                event="run_created",
                actor="system",
                message=f"Created run #{issue_number} on runtime {assigned_runtime_version}",
            )
        )
        self._runs[run_id] = run
        return run

    def build_request(self, run_id: str) -> RunRequest:
        run = self._runs[run_id]
        return RunRequest(
            run_id=run.run_id,
            worker=run.current_worker,
            stage=run.current_stage,
            repo=run.repo,
            issue_number=run.issue_number,
            branch=run.branch,
            workspace_ref=run.workspace_ref,
            artifacts=list(run.artifacts),
            context={"runtime_version": run.runtime_version},
        )

    def apply_result(self, result: RunResult, *, next_stage: str | None = None) -> RunState:
        run = self._runs[result.run_id]
        event = StageEvent(
            run_id=run.run_id,
            stage=result.stage,
            event=f"runtime_{result.status.value}",
            actor=result.worker.value,
            message=result.summary,
        )
        if run.events and run.events[-1].model_dump() == event.model_dump():
            return run

        existing_ids = {artifact.artifact_id for artifact in run.artifacts}
        for artifact in result.artifacts:
            if artifact.artifact_id not in existing_ids:
                run.artifacts.append(artifact)
        run.updated_at = _utc_now()
        run.events.append(event)

        if result.status in {RunStatus.FAILED, RunStatus.BLOCKED}:
            run.status = result.status
            run.current_stage = result.status.value
            return run

        run.status = RunStatus.RUNNING
        if next_stage is not None:
            self.advance_stage(run.run_id, next_stage)
        return run

    def advance_stage(
        self,
        run_id: str,
        next_stage: str,
        *,
        next_worker: WorkerName | None = None,
    ) -> RunState:
        run = self._runs[run_id]
        allowed = _ALLOWED_STAGE_TRANSITIONS.get(run.current_stage, ())
        if next_stage not in allowed:
            raise ValueError(f"invalid stage transition: {run.current_stage} -> {next_stage}")

        run.current_stage = next_stage
        if next_worker is not None:
            run.current_worker = next_worker
        if next_stage == "completed":
            run.status = RunStatus.PASSED
        elif next_stage == "failed":
            run.status = RunStatus.FAILED
        elif next_stage == "blocked":
            run.status = RunStatus.BLOCKED
        else:
            run.status = RunStatus.RUNNING
        run.updated_at = _utc_now()
        run.events.append(
            StageEvent(
                run_id=run.run_id,
                stage=next_stage,
                event="stage_advanced",
                actor="system",
                message=f"Advanced to {next_stage}",
            )
        )
        return run

    def get_run(self, run_id: str) -> RunState:
        return self._runs[run_id]

    def can_complete(
        self,
        run_id: str,
        *,
        ci_passed: bool,
        coverage_pct: float,
        quality_passed: bool,
        min_coverage_pct: float = 85.0,
    ) -> bool:
        run = self._runs[run_id]
        return (
            run.current_stage == "quality_checks_passed"
            and ci_passed
            and quality_passed
            and coverage_pct >= min_coverage_pct
        )

    def complete_run_if_ready(
        self,
        run_id: str,
        *,
        ci_passed: bool,
        coverage_pct: float,
        quality_passed: bool,
        min_coverage_pct: float = 85.0,
    ) -> RunState:
        if not self.can_complete(
            run_id,
            ci_passed=ci_passed,
            coverage_pct=coverage_pct,
            quality_passed=quality_passed,
            min_coverage_pct=min_coverage_pct,
        ):
            raise ValueError("completion gates not satisfied")
        return self.advance_stage(run_id, "completed")

    def fail_run(self, run_id: str, *, error: str) -> RunState:
        """Mark a run as failed with an error message."""
        run = self._runs[run_id]
        run.status = RunStatus.FAILED
        run.current_stage = "failed"
        run.updated_at = _utc_now()
        run.events.append(
            StageEvent(
                run_id=run.run_id,
                stage="failed",
                event="run_failed",
                actor="system",
                message=error,
            )
        )
        return run

    def schedule_retry(self, run_id: str, *, reason: str) -> RunState:
        run = self._runs[run_id]
        run.retries[run.current_stage] = run.retries.get(run.current_stage, 0) + 1
        run.status = RunStatus.RUNNING
        run.updated_at = _utc_now()
        run.events.append(
            StageEvent(
                run_id=run.run_id,
                stage=run.current_stage,
                event="retry_scheduled",
                actor="system",
                message=reason,
            )
        )
        return run

    def dump_runs(self) -> list[dict[str, object]]:
        """Serialize run state for persistence."""
        payload: list[dict[str, object]] = []
        for run in self._runs.values():
            payload.append(
                {
                    "run_id": run.run_id,
                    "repo": run.repo,
                    "issue_number": run.issue_number,
                    "branch": run.branch,
                    "workspace_ref": run.workspace_ref,
                    "current_stage": run.current_stage,
                    "current_worker": run.current_worker.value,
                    "status": run.status.value,
                    "runtime_version": run.runtime_version,
                    "artifacts": [artifact.model_dump() for artifact in run.artifacts],
                    "events": [event.model_dump(mode="json") for event in run.events],
                    "retries": dict(run.retries),
                }
            )
        return payload

    def load_runs(self, payload: list[dict[str, object]]) -> None:
        """Restore run state from persisted payload."""
        self._runs = {}
        for item in payload:
            from stronghold.builders.contracts import ArtifactRef, StageEvent

            run = RunState(
                run_id=str(item["run_id"]),
                repo=str(item["repo"]),
                issue_number=int(str(cast("str", item.get("issue_number", "0")))),
                branch=str(item["branch"]),
                workspace_ref=str(item["workspace_ref"]),
                current_stage=str(item["current_stage"]),
                current_worker=WorkerName(str(item["current_worker"])),
                runtime_version=str(item.get("runtime_version", "v1")),
                status=RunStatus(str(item["status"])),
                artifacts=[
                    ArtifactRef.model_validate(artifact)
                    for artifact in list(cast("list[object]", item.get("artifacts", [])))
                ],
                events=[
                    StageEvent.model_validate(event)
                    for event in list(cast("list[object]", item.get("events", [])))
                ],
                retries={
                    str(k): int(str(v))
                    for k, v in dict(cast("dict[str, object]", item.get("retries", {}))).items()
                },
            )
            run.updated_at = _utc_now()
            self._runs[run.run_id] = run
