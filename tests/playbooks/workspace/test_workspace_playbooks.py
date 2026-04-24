"""Workspace playbooks: status, commit (dry-run + live), read."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.workspace.commit_workspace import commit_workspace
from stronghold.playbooks.workspace.read_workspace import read_workspace
from stronghold.playbooks.workspace.workspace_status import workspace_status
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.tool import ToolResult

if TYPE_CHECKING:
    import pytest


class _FakeWorkspaceManager:
    def __init__(self, responses: dict[str, ToolResult]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        action = arguments.get("action", "")
        return self._responses.get(
            action,
            ToolResult(success=False, error=f"no fake for {action}"),
        )


def _ctx() -> PlaybookContext:
    return PlaybookContext(auth=SYSTEM_AUTH)


async def test_workspace_status_renders_clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager(
        {
            "status": ToolResult(
                content=json.dumps(
                    {
                        "branch": "mason/42",
                        "worktree": "/ws/acme/widget/42",
                        "ahead": 0,
                        "behind": 0,
                        "dirty": False,
                    }
                ),
                success=True,
            )
        }
    )
    mod = sys.modules["stronghold.playbooks.workspace.workspace_status"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await workspace_status(
        {"owner": "acme", "repo": "widget", "issue_number": 42},
        _ctx(),
    )
    assert "mason/42" in brief.to_markdown()
    assert brief.flags == ()


async def test_workspace_status_flags_dirty_and_ahead(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager(
        {
            "status": ToolResult(
                content=json.dumps(
                    {
                        "branch": "mason/7",
                        "worktree": "/ws/acme/widget/7",
                        "ahead": 2,
                        "behind": 1,
                        "dirty": True,
                    }
                ),
                success=True,
            )
        }
    )
    mod = sys.modules["stronghold.playbooks.workspace.workspace_status"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await workspace_status(
        {"owner": "acme", "repo": "widget", "issue_number": 7},
        _ctx(),
    )
    assert "uncommitted changes" in brief.flags
    assert any("ahead" in f for f in brief.flags)


async def test_workspace_status_failure_surfaces_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager({"status": ToolResult(success=False, error="no worktree")})
    mod = sys.modules["stronghold.playbooks.workspace.workspace_status"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await workspace_status(
        {"owner": "acme", "repo": "widget", "issue_number": 99},
        _ctx(),
    )
    assert "workspace-error" in brief.flags
    assert "no worktree" in brief.summary


async def test_commit_workspace_dry_run_skips_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager(
        {
            "status": ToolResult(
                content=json.dumps({"dirty": True, "branch": "mason/1"}), success=True
            )
        }
    )
    mod = sys.modules["stronghold.playbooks.workspace.commit_workspace"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await commit_workspace(
        {
            "owner": "acme",
            "repo": "widget",
            "issue_number": 1,
            "message": "fix: x",
            "dry_run": True,
        },
        _ctx(),
    )
    assert "Dry-run" in brief.title
    # No commit call in dry-run
    actions = [c["action"] for c in fake.calls]
    assert "commit" not in actions


async def test_commit_workspace_live_commits_and_pushes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager(
        {
            "commit": ToolResult(content=json.dumps({"sha": "abc"}), success=True),
            "push": ToolResult(content=json.dumps({"pushed": True}), success=True),
        }
    )
    mod = sys.modules["stronghold.playbooks.workspace.commit_workspace"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await commit_workspace(
        {
            "owner": "acme",
            "repo": "widget",
            "issue_number": 1,
            "message": "feat: y",
            "dry_run": False,
        },
        _ctx(),
    )
    assert "Committed" in brief.title
    actions = [c["action"] for c in fake.calls]
    assert "commit" in actions
    assert "push" in actions


async def test_commit_workspace_honors_push_false(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager(
        {"commit": ToolResult(content=json.dumps({"sha": "abc"}), success=True)}
    )
    mod = sys.modules["stronghold.playbooks.workspace.commit_workspace"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    await commit_workspace(
        {
            "owner": "acme",
            "repo": "widget",
            "issue_number": 1,
            "message": "feat: z",
            "push": False,
            "dry_run": False,
        },
        _ctx(),
    )
    actions = [c["action"] for c in fake.calls]
    assert "push" not in actions


async def test_commit_workspace_failure_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeWorkspaceManager({"commit": ToolResult(success=False, error="nothing to commit")})
    mod = sys.modules["stronghold.playbooks.workspace.commit_workspace"]
    monkeypatch.setattr(mod, "WorkspaceManager", lambda: fake)

    brief = await commit_workspace(
        {
            "owner": "acme",
            "repo": "widget",
            "issue_number": 1,
            "message": "m",
            "dry_run": False,
        },
        _ctx(),
    )
    assert "commit-error" in brief.flags


async def test_read_workspace_lists_tree() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        p = Path(workspace)
        (p / "a.txt").write_text("alpha")
        (p / "b.txt").write_text("beta")

        brief = await read_workspace(
            {"workspace": workspace, "path": "."},
            _ctx(),
        )
        md = brief.to_markdown()
        assert "a.txt" in md
        assert "b.txt" in md
        assert "Tree" in md


async def test_read_workspace_samples_file_contents() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        p = Path(workspace)
        (p / "hello.txt").write_text("greetings, traveller")

        brief = await read_workspace(
            {
                "workspace": workspace,
                "path": ".",
                "read_files": ["hello.txt"],
            },
            _ctx(),
        )
        md = brief.to_markdown()
        assert "greetings, traveller" in md
        assert "Contents: hello.txt" in md


async def test_read_workspace_reports_missing_file() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        brief = await read_workspace(
            {
                "workspace": workspace,
                "path": ".",
                "read_files": ["missing.txt"],
            },
            _ctx(),
        )
        md = brief.to_markdown()
        assert "Contents: missing.txt" in md
        assert "_error" in md
