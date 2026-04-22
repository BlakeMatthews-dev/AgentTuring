"""Behavioral tests for WorkspaceManager, driven by spec ``tools_workspace.md``.

Complements ``test_workspace_coverage.py``; targets uncovered branches:
  - 80-81  (_resolve_base_dir OSError fallback)
  - 105    (dispatcher unknown-handler guard)
  - 138-154 (_create happy-path, including "exists" short-circuit)
  - 193-195 (_push missing worktree)
  - 205-212 (_cleanup with cached-repo iteration and rmtree fallback)

Uses a local bare git repo as the "remote" to avoid any network I/O.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from stronghold.tools import workspace
from stronghold.tools.workspace import WorkspaceManager


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_bare_repo_with_main(bare_dir: Path) -> None:
    """Create a bare repo with a populated 'main' branch."""
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare_dir)],
        check=True, capture_output=True,
    )
    seed = bare_dir.parent / (bare_dir.name + "_seed")
    subprocess.run(
        ["git", "clone", str(bare_dir), str(seed)],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "checkout", "-b", "main"], cwd=seed, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "seed@test.local"],
        cwd=seed, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Seed"],
        cwd=seed, check=True, capture_output=True,
    )
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=seed, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"], cwd=seed, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=seed, check=True, capture_output=True,
    )
    shutil.rmtree(seed)


def _clone_local_bare_into_manager(
    manager: WorkspaceManager,
    bare: Path,
    owner: str = "o",
    repo: str = "r",
) -> Path:
    """Populate manager's _repos cache with a locally cloned bare repo."""
    repo_dir = manager._base / "repos" / repo
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(bare), str(repo_dir)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "mason@stronghold.local"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Mason"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    manager._repos[f"{owner}/{repo}"] = repo_dir
    return repo_dir


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceManager:
    with patch.object(WorkspaceManager, "_resolve_base_dir", return_value=tmp_path):
        return WorkspaceManager()


# ─────────────────────────────────────────────────────────────────────
# _resolve_base_dir
# ─────────────────────────────────────────────────────────────────────


class TestResolveBaseDir:
    def test_resolve_base_uses_configured_root_when_writable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        target = tmp_path / "wsroot"
        monkeypatch.setattr(workspace, "DEFAULT_WORKSPACE_ROOT", target)
        result = WorkspaceManager._resolve_base_dir()
        assert result == target
        assert target.is_dir()

    def test_resolve_base_falls_back_to_tempdir_on_oserror(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        bad = Path("/proc/1/definitely-not-writable")
        monkeypatch.setattr(workspace, "DEFAULT_WORKSPACE_ROOT", bad)
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.workspace"):
            result = WorkspaceManager._resolve_base_dir()
        assert result.name == "stronghold-workspace"
        assert result.is_dir()
        assert any("Workspace root unavailable" in r.message for r in caplog.records)

    def test_resolve_base_raises_when_all_candidates_unwritable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def always_fail(self, *args, **kwargs):
            raise OSError("no write")

        monkeypatch.setattr(Path, "mkdir", always_fail)
        with pytest.raises(RuntimeError, match="No writable workspace root available"):
            WorkspaceManager._resolve_base_dir()


# ─────────────────────────────────────────────────────────────────────
# execute() dispatcher
# ─────────────────────────────────────────────────────────────────────


class TestExecuteDispatcher:
    async def test_execute_unknown_action_returns_error(self, manager) -> None:
        result = await manager.execute({"action": "spin"})
        assert not result.success
        assert result.error == "Unknown action: spin"

    async def test_execute_missing_action_returns_error(self, manager) -> None:
        result = await manager.execute({})
        assert not result.success
        assert result.error == "Unknown action: "

    async def test_execute_handler_exception_wraps_as_error_result(
        self, manager, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        def boom(args):
            raise RuntimeError("ouch")

        monkeypatch.setattr(manager, "_create", boom)
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.workspace"):
            result = await manager.execute({
                "action": "create", "owner": "o", "repo": "r", "issue_number": 1,
            })
        assert not result.success
        assert "ouch" in (result.error or "")
        assert any("Workspace error" in r.message for r in caplog.records)

    async def test_execute_success_serializes_json(
        self, manager, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(manager, "_status", lambda args: {"status": "active"})
        result = await manager.execute({"action": "status", "issue_number": 5})
        assert result.success
        assert json.loads(result.content) == {"status": "active"}


# ─────────────────────────────────────────────────────────────────────
# _ensure_clone
# ─────────────────────────────────────────────────────────────────────


class TestEnsureClone:
    def test_ensure_clone_uses_token_url_when_env_set(
        self, manager, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "gh_abc")
        with patch.object(WorkspaceManager, "_run") as mock_run:
            mock_run.return_value = ""
            manager._ensure_clone("o", "r")
            clone_args = mock_run.call_args_list[0][0][0]
            assert clone_args[0] == "git" and clone_args[1] == "clone"
            assert clone_args[3] == "https://x-access-token:gh_abc@github.com/o/r.git"

    def test_ensure_clone_no_token_uses_anonymous_url(
        self, manager, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch.object(WorkspaceManager, "_run") as mock_run:
            mock_run.return_value = ""
            manager._ensure_clone("o", "r")
            assert mock_run.call_args_list[0][0][0][3] == "https://github.com/o/r.git"

    def test_ensure_clone_caches_by_owner_repo(
        self, manager, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch.object(WorkspaceManager, "_run") as mock_run:
            mock_run.return_value = ""
            first = manager._ensure_clone("o", "r")
            n = len(mock_run.call_args_list)
            second = manager._ensure_clone("o", "r")
        assert second == first
        assert len(mock_run.call_args_list) == n

    def test_ensure_clone_picks_up_preexisting_dir_without_clone(
        self, manager,
    ) -> None:
        repo_dir = manager._base / "repos" / "r"
        repo_dir.mkdir(parents=True)
        with patch.object(WorkspaceManager, "_run") as mock_run:
            result = manager._ensure_clone("o", "r")
        assert result == repo_dir
        mock_run.assert_not_called()

    def test_ensure_clone_configures_git_identity(
        self, manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        real_run = WorkspaceManager._run

        def intercept(cmd, cwd=None):
            if cmd[:2] == ["git", "clone"]:
                cmd = list(cmd)
                cmd[3] = str(bare)
            return real_run(cmd, cwd=cwd)

        monkeypatch.setattr(WorkspaceManager, "_run", staticmethod(intercept))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        manager._ensure_clone("o", "r")
        cloned = manager._base / "repos" / "r"
        email = subprocess.run(
            ["git", "config", "--get", "user.email"],
            cwd=cloned, capture_output=True, text=True, check=True,
        ).stdout.strip()
        name = subprocess.run(
            ["git", "config", "--get", "user.name"],
            cwd=cloned, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert email == "mason@stronghold.local"
        assert name == "Mason"


# ─────────────────────────────────────────────────────────────────────
# _create
# ─────────────────────────────────────────────────────────────────────


class TestCreateWorktree:
    async def test_create_new_worktree_returns_created(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)

        result = await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 7,
        })
        assert result.success, result.error
        data = json.loads(result.content)
        assert data["status"] == "created"
        assert data["branch"] == "mason/7"
        wt = manager._base / "worktrees" / "mason-7"
        assert Path(data["path"]) == wt
        assert wt.exists()
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=wt, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert current == "mason/7"

    async def test_create_honors_explicit_branch_name(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        result = await manager.execute({
            "action": "create", "owner": "o", "repo": "r",
            "issue_number": 11, "branch": "feature/xyz",
        })
        data = json.loads(result.content)
        assert data["branch"] == "feature/xyz"
        wt = manager._base / "worktrees" / "mason-11"
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=wt, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert current == "feature/xyz"

    async def test_create_existing_worktree_returns_exists_without_reinit(
        self, manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 5,
        })

        call_log: list[list[str]] = []
        real_run = WorkspaceManager._run

        def spy(cmd, cwd=None):
            call_log.append(list(cmd))
            return real_run(cmd, cwd=cwd)

        monkeypatch.setattr(WorkspaceManager, "_run", staticmethod(spy))

        result = await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 5,
        })
        data = json.loads(result.content)
        assert data["status"] == "exists"
        assert not any(c[:3] == ["git", "worktree", "add"] for c in call_log)

    async def test_create_fetches_origin_main_first(
        self, manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)

        call_log: list[list[str]] = []
        real_run = WorkspaceManager._run

        def spy(cmd, cwd=None):
            call_log.append(list(cmd))
            return real_run(cmd, cwd=cwd)

        monkeypatch.setattr(WorkspaceManager, "_run", staticmethod(spy))

        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 3,
        })

        fetch_idx = next(
            i for i, c in enumerate(call_log) if c[:4] == ["git", "fetch", "origin", "main"]
        )
        add_idx = next(
            i for i, c in enumerate(call_log) if c[:3] == ["git", "worktree", "add"]
        )
        assert fetch_idx < add_idx


# ─────────────────────────────────────────────────────────────────────
# _status
# ─────────────────────────────────────────────────────────────────────


class TestStatus:
    async def test_status_returns_not_found_when_no_worktree(self, manager) -> None:
        result = await manager.execute({"action": "status", "issue_number": 999})
        assert result.success
        assert json.loads(result.content) == {"status": "not_found"}

    async def test_status_clean_worktree_has_empty_changes(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 21,
        })
        result = await manager.execute({"action": "status", "issue_number": 21})
        assert result.success
        data = json.loads(result.content)
        assert data["status"] == "active"
        assert data["changes"] == []
        assert data["branch"] == "mason/21"

    async def test_status_lists_modified_files(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 22,
        })
        wt = manager._base / "worktrees" / "mason-22"
        (wt / "newfile.txt").write_text("hi")
        result = await manager.execute({"action": "status", "issue_number": 22})
        data = json.loads(result.content)
        assert data["status"] == "active"
        assert any("newfile.txt" in c for c in data["changes"])


# ─────────────────────────────────────────────────────────────────────
# _commit
# ─────────────────────────────────────────────────────────────────────


class TestCommit:
    async def test_commit_missing_worktree_returns_error(self, manager) -> None:
        result = await manager.execute({"action": "commit", "issue_number": 9999})
        assert result.success
        data = json.loads(result.content)
        assert data == {"status": "error", "error": "worktree not found"}

    async def test_commit_with_no_changes_allows_empty(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 30,
        })
        wt = manager._base / "worktrees" / "mason-30"
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt, check=True, capture_output=True, text=True,
        ).stdout.strip()

        result = await manager.execute({
            "action": "commit", "issue_number": 30, "message": "empty test",
        })
        data = json.loads(result.content)
        assert data["status"] == "committed"
        assert data["sha"] != base_sha
        assert len(data["sha"]) == 40

    async def test_commit_honors_custom_message(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 31,
        })
        await manager.execute({
            "action": "commit", "issue_number": 31, "message": "custom msg",
        })
        wt = manager._base / "worktrees" / "mason-31"
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=wt, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert msg == "custom msg"

    async def test_commit_default_message_contains_issue_number(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 42,
        })
        await manager.execute({"action": "commit", "issue_number": 42})
        wt = manager._base / "worktrees" / "mason-42"
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=wt, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert "#42" in msg

    async def test_commit_returns_40_char_sha(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 50,
        })
        result = await manager.execute({
            "action": "commit", "issue_number": 50, "message": "x",
        })
        sha = json.loads(result.content)["sha"]
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)


# ─────────────────────────────────────────────────────────────────────
# _push
# ─────────────────────────────────────────────────────────────────────


class TestPush:
    async def test_push_missing_worktree_returns_error(self, manager) -> None:
        result = await manager.execute({"action": "push", "issue_number": 9999})
        assert result.success
        data = json.loads(result.content)
        assert data == {"status": "error", "error": "worktree not found"}

    async def test_push_invokes_upstream_tracking(
        self, manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 60,
        })

        call_log: list[list[str]] = []
        real_run = WorkspaceManager._run

        def spy(cmd, cwd=None):
            call_log.append(list(cmd))
            return real_run(cmd, cwd=cwd)

        monkeypatch.setattr(WorkspaceManager, "_run", staticmethod(spy))
        result = await manager.execute({"action": "push", "issue_number": 60})
        assert result.success
        push_calls = [c for c in call_log if c[:2] == ["git", "push"]]
        assert push_calls == [["git", "push", "-u", "origin", "mason/60"]]

    async def test_push_returns_current_branch(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r",
            "issue_number": 5, "branch": "mason/5",
        })
        result = await manager.execute({"action": "push", "issue_number": 5})
        data = json.loads(result.content)
        assert data == {"status": "pushed", "branch": "mason/5"}

    async def test_push_failure_propagates_as_error_result(
        self, manager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 61,
        })

        real_run = WorkspaceManager._run

        def fail_push(cmd, cwd=None):
            if cmd[:2] == ["git", "push"]:
                raise RuntimeError("git push: denied")
            return real_run(cmd, cwd=cwd)

        monkeypatch.setattr(WorkspaceManager, "_run", staticmethod(fail_push))
        result = await manager.execute({"action": "push", "issue_number": 61})
        assert not result.success
        assert "denied" in (result.error or "")


# ─────────────────────────────────────────────────────────────────────
# _cleanup
# ─────────────────────────────────────────────────────────────────────


class TestCleanup:
    async def test_cleanup_missing_worktree_returns_not_found(self, manager) -> None:
        result = await manager.execute({"action": "cleanup", "issue_number": 9999})
        assert result.success
        assert json.loads(result.content) == {"status": "not_found"}

    async def test_cleanup_removes_existing_worktree(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        _clone_local_bare_into_manager(manager, bare)
        await manager.execute({
            "action": "create", "owner": "o", "repo": "r", "issue_number": 70,
        })
        wt = manager._base / "worktrees" / "mason-70"
        assert wt.exists()
        result = await manager.execute({"action": "cleanup", "issue_number": 70})
        assert result.success
        assert json.loads(result.content) == {"status": "cleaned"}
        assert not wt.exists()

    async def test_cleanup_fallback_rmtree_when_git_worktree_fails(
        self, manager,
    ) -> None:
        wt = manager._base / "worktrees" / "mason-80"
        wt.mkdir(parents=True)
        (wt / "f.txt").write_text("x")
        manager._repos.clear()
        result = await manager.execute({"action": "cleanup", "issue_number": 80})
        assert result.success
        assert json.loads(result.content) == {"status": "cleaned"}
        assert not wt.exists()

    async def test_cleanup_tries_each_cached_repo_until_one_succeeds(
        self, manager, tmp_path: Path,
    ) -> None:
        bare = tmp_path / "bare.git"
        _make_bare_repo_with_main(bare)
        good_repo = _clone_local_bare_into_manager(manager, bare, owner="good")
        bad_repo = tmp_path / "nonexistent-repo"
        manager._repos = {"bad/r": bad_repo, "good/r": good_repo}
        wt = manager._base / "worktrees" / "mason-90"
        subprocess.run(
            ["git", "worktree", "add", str(wt), "-b", "mason/90", "origin/main"],
            cwd=good_repo, check=True, capture_output=True,
        )
        assert wt.exists()
        result = await manager.execute({"action": "cleanup", "issue_number": 90})
        assert result.success
        assert json.loads(result.content) == {"status": "cleaned"}
        assert not wt.exists()


# ─────────────────────────────────────────────────────────────────────
# _run
# ─────────────────────────────────────────────────────────────────────


class TestRun:
    def test_run_returns_stdout_on_success(self) -> None:
        out = WorkspaceManager._run(["echo", "hi"])
        assert out.strip() == "hi"

    def test_run_raises_runtime_error_on_nonzero(self) -> None:
        with pytest.raises(RuntimeError, match=r"^false: "):
            WorkspaceManager._run(["false"])

    def test_run_raises_when_stderr_present(self) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            WorkspaceManager._run(["sh", "-c", "echo boom 1>&2; exit 3"])
