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


# ---- name property ----


def test_name(manager):
    assert manager.name == "workspace"


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


# ---- _ensure_clone uses token via credential config (not URL) ----


def test_ensure_clone_url_with_token(manager):
    """When GITHUB_TOKEN is set, auth is passed via git -c extraheader, not URL."""
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}),
        patch.object(WorkspaceManager, "_run") as mock_run,
    ):
        mock_run.return_value = ""
        manager._ensure_clone("owner", "repo")
        clone_call = mock_run.call_args_list[0]
        cmd = clone_call[0][0]
        # URL must be plain HTTPS (no embedded token)
        url = cmd[-2]  # second-to-last: the URL
        assert url == "https://github.com/owner/repo.git"
        assert "x-access-token" not in url
        # Token is passed via -c http.extraheader (transient, not in .git/config)
        assert "-c" in cmd
        header_idx = cmd.index("-c") + 1
        assert "Authorization: Bearer ghp_test123" in cmd[header_idx]


def test_ensure_clone_url_without_token(manager):
    """Without GITHUB_TOKEN, clone URL uses plain HTTPS and no -c header."""
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(WorkspaceManager, "_run") as mock_run,
    ):
        mock_run.return_value = ""
        manager._ensure_clone("owner", "repo")
        clone_call = mock_run.call_args_list[0]
        cmd = clone_call[0][0]
        url = cmd[-2]  # second-to-last: the URL
        assert "x-access-token" not in url
        assert url == "https://github.com/owner/repo.git"
        # No -c flag when there's no token
        assert "-c" not in cmd


# ---- status with real git worktree ----


async def test_status_active_worktree(manager, tmp_path):
    """Test status on an actual git-initialized worktree directory."""
    wt_dir = tmp_path / "worktrees" / "mason-42"
    wt_dir.mkdir(parents=True)
    subprocess.run(["git", "init", str(wt_dir)], capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=wt_dir, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wt_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=wt_dir, capture_output=True
    )

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
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=wt_dir, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wt_dir, capture_output=True)

    result = await manager.execute(
        {
            "action": "commit",
            "issue_number": 99,
            "message": "test commit",
        }
    )
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


# ---- security: token not in clone URL (H2) ----


def test_ensure_clone_token_not_in_url(manager):
    """H2: GitHub token must NOT appear in the clone URL.

    Embedding tokens in URLs leaks them to: ps output, /proc/*/cmdline,
    git error messages, and .git/config. The token may appear in a
    transient -c config value (which is acceptable), but must never be
    part of the URL argument itself.
    """
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret_token_123"}),
        patch.object(WorkspaceManager, "_run") as mock_run,
    ):
        mock_run.return_value = ""
        manager._ensure_clone("owner", "repo")
        clone_call = mock_run.call_args_list[0]
        cmd = clone_call[0][0]
        # The URL argument (second-to-last) must not contain the token
        url = cmd[-2]
        assert "ghp_secret_token_123" not in url, f"Token leaked into clone URL: {url}"
        assert "x-access-token" not in url, f"Token embedded in URL via x-access-token: {url}"


def test_ensure_clone_token_not_in_error_messages(manager, tmp_path):
    """H2: If clone fails, error message must not contain the token."""
    # Don't pre-create repo dir so _ensure_clone tries to clone
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret_token_456"}),
        patch.object(WorkspaceManager, "_run") as mock_run,
    ):
        # First call (clone) raises; subsequent calls (config) shouldn't happen
        mock_run.side_effect = RuntimeError("git clone: authentication failed")
        try:
            manager._ensure_clone("owner", "repo")
        except RuntimeError as e:
            # The error message must not contain the token
            assert "ghp_secret_token_456" not in str(e)


def test_ensure_clone_uses_credential_config(manager):
    """H2: Clone should use git -c http.extraheader for auth, not URL-embedded tokens."""
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test_cred_789"}),
        patch.object(WorkspaceManager, "_run") as mock_run,
    ):
        mock_run.return_value = ""
        manager._ensure_clone("owner", "repo")
        # The clone URL should be plain HTTPS without credentials
        clone_call = mock_run.call_args_list[0]
        cmd = clone_call[0][0]
        url = cmd[-2]  # second-to-last arg is the URL
        assert url == "https://github.com/owner/repo.git"
        assert "x-access-token" not in url
        # Auth must be via -c extraheader
        assert "-c" in cmd
        header_idx = cmd.index("-c") + 1
        assert "http.https://github.com/.extraheader" in cmd[header_idx]


def test_run_strips_token_from_errors(manager):
    """H2: _run must sanitize tokens out of error messages when git fails."""
    # If the token somehow ends up in stderr, _run should strip it
    with (
        patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_leaked_in_stderr"}),
        patch("subprocess.run") as mock_subprocess,
    ):
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="fatal: Authentication failed for https://x-access-token:ghp_leaked_in_stderr@github.com/o/r.git",
        )
        try:
            WorkspaceManager._run(["git", "clone", "url"])
        except RuntimeError as e:
            assert "ghp_leaked_in_stderr" not in str(e)
