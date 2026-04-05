"""Shared Builders 2.0 contracts for orchestrator and runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkerName(StrEnum):
    """Known Builders runtime roles."""

    FRANK = "frank"
    MASON = "mason"
    AUDITOR = "auditor"
    PIPER = "piper"
    GLAZIER = "glazier"


class RunStatus(StrEnum):
    """Workflow state tracked by Stronghold core."""

    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ArtifactRef(BaseModel):
    """Reference to a durable artifact."""

    artifact_id: str = Field(default_factory=lambda: f"art_{uuid4().hex}")
    type: str
    path: str
    producer: str
    content_type: str = "application/json"
    version: str = "1"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    """Task payload sent from core to Builders runtime."""

    run_id: str
    worker: WorkerName
    stage: str
    repo: str
    issue_number: int
    branch: str
    workspace_ref: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    """Result payload returned from Builders runtime to core."""

    run_id: str
    worker: WorkerName
    stage: str
    status: RunStatus
    summary: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


class StageEvent(BaseModel):
    """Durable workflow event."""

    run_id: str
    stage: str
    event: str
    actor: str
    timestamp: datetime = Field(default_factory=_utc_now)
    message: str


class WorkerStatus(BaseModel):
    """Worker health and capability advertisement."""

    worker: WorkerName
    version: str
    status: str
    capabilities: list[str] = Field(default_factory=list)
