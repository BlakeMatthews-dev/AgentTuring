"""Tests for WorkspaceManager — git worktree management.

Tests the execute dispatch, _resolve_base_dir, and error paths.
Avoids real git clone by testing methods that do not require a remote.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from stronghold.tools.workspace import WorkspaceManager


@pytest.fixture
def manager(tmp_path):
    """WorkspaceManager with a temp base directory."""
    with patch.object(WorkspaceManager, "_resolve_base_dir", return_value=tmp_path):
        mgr = WorkspaceManager()
    return mgr


# ---- execute dispatch ----

async def test_execute_unknown_action(manager):
    result = await manager.execute({"action": "unknown"})
    assert result.success is False
    assert "Unknown action" in result.error


async def test_execute_status_not_found(manager):
    result = await manager.execute({"action": "status", "issue_number": 9999})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "not_found"


async def test_execute_commit_not_found(manager):
    result = await manager.execute({"action": "commit", "issue_number": 9999})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "error"
    assert "not found" in data["error"]


async def test_execute_push_not_found(manager):
    result = await manager.execute({"action": "push", "issue_number": 9999})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "error"
    assert "not found" in data["error"]


async def test_execute_cleanup_not_found(manager):
    result = await manager.execute({"action": "cleanup", "issue_number": 9999})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "not_found"


# ---- _resolve_base_dir ----

def test_resolve_base_dir_uses_default(tmp_path):
    with patch("stronghold.tools.workspace.DEFAULT_WORKSPACE_ROOT", tmp_path / "ws"):
        mgr = WorkspaceManager()
        assert mgr._base == tmp_path / "ws"
        assert (tmp_path / "ws").is_dir()


def test_resolve_base_dir_fallback(tmp_path):
    """Falls back to temp dir when default is not writable."""
    bad_path = Path("/proc/stronghold-workspace-test-nonexist")
    with patch("stronghold.tools.workspace.DEFAULT_WORKSPACE_ROOT", bad_path):
        mgr = WorkspaceManager()
        assert "stronghold-workspace" in str(mgr._base)
        assert mgr._base.is_dir()


# ---- _ensure_clone uses token when available ----

def test_ensure_clone_url_with_token(manager):
    """When GITHUB_TOKEN is set, clone URL includes it."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
        with patch.object(WorkspaceManager, "_run") as mock_run:
            mock_run.return_value = ""
            manager._ensure_clone("owner", "repo")
            clone_call = mock_run.call_args_list[0]
            url = clone_call[0][0][3]  # 4th element of the git clone command
            assert "ghp_test123" in url


def test_ensure_clone_url_without_token(manager):
    """Without GITHUB_TOKEN, clone URL uses plain HTTPS."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove GITHUB_TOKEN if present
        os.environ.pop("GITHUB_TOKEN", None)
        with patch.object(WorkspaceManager, "_run") as mock_run:
            mock_run.return_value = ""
            manager._ensure_clone("owner", "repo")
            clone_call = mock_run.call_args_list[0]
            url = clone_call[0][0][3]
            assert "x-access-token" not in url
            assert "https://github.com/owner/repo.git" == url


# ---- status with real git worktree ----

async def test_status_active_worktree(manager, tmp_path):
    """Test status on an actual git-initialized worktree directory."""
    wt_dir = tmp_path / "worktrees" / "mason-42"
    wt_dir.mkdir(parents=True)
    subprocess.run(["git", "init", str(wt_dir)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=wt_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wt_dir, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=wt_dir, capture_output=True)

    result = await manager.execute({"action": "status", "issue_number": 42})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "active"
    assert data["changes"] == []


# ---- commit with real git ----

async def test_commit_in_worktree(manager, tmp_path):
    """Test commit on a real git repo."""
    wt_dir = tmp_path / "worktrees" / "mason-99"
    wt_dir.mkdir(parents=True)
    subprocess.run(["git", "init", str(wt_dir)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=wt_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wt_dir, capture_output=True)

    result = await manager.execute({
        "action": "commit",
        "issue_number": 99,
        "message": "test commit",
    })
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "committed"
    assert len(data["sha"]) == 40


# ---- cleanup with real directory ----

async def test_cleanup_removes_directory(manager, tmp_path):
    """Cleanup removes the worktree directory even without a parent repo."""
    wt_dir = tmp_path / "worktrees" / "mason-77"
    wt_dir.mkdir(parents=True)
    (wt_dir / "file.txt").write_text("x")

    result = await manager.execute({"action": "cleanup", "issue_number": 77})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "cleaned"
    assert not wt_dir.exists()


# ---- _run error handling ----

def test_run_raises_on_failure(tmp_path):
    """_run raises RuntimeError when the git command fails."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(RuntimeError, match="git"):
        WorkspaceManager._run(["git", "status"], cwd=empty_dir)
