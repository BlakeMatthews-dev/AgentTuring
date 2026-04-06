"""Minimal Builders platform services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from stronghold.builders.contracts import ArtifactRef, StageEvent


@dataclass(frozen=True)
class WorkspaceRef:
    """Stable workspace reference."""

    workspace_id: str
    run_id: str
    repo: str
    branch: str
    path: str
    status: str = "active"


class InMemoryWorkspaceService:
    """Creates and resolves stable workspace refs."""

    def __init__(self) -> None:
        self._workspaces: dict[str, WorkspaceRef] = {}

    def create(self, *, run_id: str, repo: str, branch: str) -> WorkspaceRef:
        workspace = WorkspaceRef(
            workspace_id=f"ws_{uuid4().hex}",
            run_id=run_id,
            repo=repo,
            branch=branch,
            path=f"/workspace/{run_id}",
        )
        self._workspaces[workspace.workspace_id] = workspace
        return workspace

    def resolve(self, workspace_id: str) -> WorkspaceRef:
        return self._workspaces[workspace_id]

    def cleanup(self, workspace_id: str, *, archive: bool = True) -> WorkspaceRef:
        current = self._workspaces[workspace_id]
        updated = WorkspaceRef(
            workspace_id=current.workspace_id,
            run_id=current.run_id,
            repo=current.repo,
            branch=current.branch,
            path=current.path,
            status="archived" if archive else "deleted",
        )
        self._workspaces[workspace_id] = updated
        return updated


class InMemoryArtifactStore:
    """Durable artifact ref store for Builders."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactRef] = {}

    def store(self, artifact: ArtifactRef) -> ArtifactRef:
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> ArtifactRef:
        return self._artifacts[artifact_id]

    def list_for_run(self, run_id: str) -> list[ArtifactRef]:
        prefix = f"runs/{run_id}/"
        return [
            artifact for artifact in self._artifacts.values() if artifact.path.startswith(prefix)
        ]


class InMemoryEventBus:
    """Simple event collector for Builders lifecycle events."""

    def __init__(self) -> None:
        self._events: list[StageEvent] = []

    def emit(self, event: StageEvent) -> None:
        self._events.append(event)

    def list_events(self, *, run_id: str | None = None) -> list[StageEvent]:
        if run_id is None:
            return list(self._events)
        return [event for event in self._events if event.run_id == run_id]


@dataclass(frozen=True)
class IssueUpdate:
    """Latest stage-aware issue update for a run."""

    run_id: str
    issue_number: int
    stage: str
    body: str


@dataclass(frozen=True)
class PullRequestRef:
    """Simple PR record for Builders workflow tests."""

    pr_number: int
    run_id: str
    repo: str
    branch: str
    title: str
    body: str


class InMemoryGitHubService:
    """Minimal GitHub-facing behavior for Builders tests."""

    def __init__(self) -> None:
        self._issue_updates: dict[tuple[str, str], IssueUpdate] = {}
        self._prs: dict[int, PullRequestRef] = {}
        self._next_pr_number = 1

    def upsert_issue_update(
        self,
        *,
        run_id: str,
        issue_number: int,
        stage: str,
        body: str,
    ) -> IssueUpdate:
        update = IssueUpdate(
            run_id=run_id,
            issue_number=issue_number,
            stage=stage,
            body=body,
        )
        self._issue_updates[(run_id, stage)] = update
        return update

    def list_issue_updates(self, *, run_id: str) -> list[IssueUpdate]:
        updates = [
            update
            for (stored_run_id, _), update in self._issue_updates.items()
            if stored_run_id == run_id
        ]
        return sorted(updates, key=lambda item: item.stage)

    def open_pr(
        self, *, run_id: str, repo: str, branch: str, title: str, body: str
    ) -> PullRequestRef:
        pr = PullRequestRef(
            pr_number=self._next_pr_number,
            run_id=run_id,
            repo=repo,
            branch=branch,
            title=title,
            body=body,
        )
        self._prs[pr.pr_number] = pr
        self._next_pr_number += 1
        return pr

    def update_pr(
        self, pr_number: int, *, title: str | None = None, body: str | None = None
    ) -> PullRequestRef:
        current = self._prs[pr_number]
        updated = PullRequestRef(
            pr_number=current.pr_number,
            run_id=current.run_id,
            repo=current.repo,
            branch=current.branch,
            title=title if title is not None else current.title,
            body=body if body is not None else current.body,
        )
        self._prs[pr_number] = updated
        return updated

    def get_pr(self, pr_number: int) -> PullRequestRef:
        return self._prs[pr_number]
