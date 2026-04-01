"""Workspace manager — git clone + worktree isolation for Mason.

Each issue gets its own worktree branched from main. Mason works
in isolation, then pushes and creates a PR. The workspace is
cleaned up after the PR is submitted.

Flow:
  1. create(issue_number, owner, repo) → clones repo (once), creates worktree
  2. Mason writes files, runs tests in the worktree
  3. commit_and_push() → stages, commits, pushes the branch
  4. cleanup() → removes worktree
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.workspace")

WORKSPACE_ROOT = Path(os.environ.get("STRONGHOLD_WORKSPACE", "/workspace"))

WORKSPACE_TOOL_DEF = ToolDefinition(
    name="workspace",
    description=(
        "Manage git worktrees for isolated code changes. "
        "Actions: create, status, commit, push, cleanup."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "status", "commit", "push", "cleanup"],
            },
            "issue_number": {"type": "integer"},
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "branch": {"type": "string"},
            "message": {"type": "string", "description": "Commit message"},
        },
        "required": ["action"],
    },
    groups=("code_gen",),
)


class WorkspaceManager:
    """Manages git repos and worktrees for Mason."""

    def __init__(self) -> None:
        self._base = WORKSPACE_ROOT
        self._base.mkdir(parents=True, exist_ok=True)
        self._repos: dict[str, Path] = {}

    @property
    def name(self) -> str:
        return "workspace"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        try:
            handler = {
                "create": self._create,
                "status": self._status,
                "commit": self._commit,
                "push": self._push,
                "cleanup": self._cleanup,
            }.get(action)
            if not handler:
                return ToolResult(success=False, error=f"Unknown action: {action}")
            result = handler(arguments)
            return ToolResult(content=json.dumps(result), success=True)
        except Exception as e:
            logger.warning("Workspace error (%s): %s", action, e)
            return ToolResult(success=False, error=str(e))

    def _ensure_clone(self, owner: str, repo: str) -> Path:
        """Clone the repo if not already cloned."""
        key = f"{owner}/{repo}"
        if key in self._repos:
            return self._repos[key]

        repo_dir = self._base / "repos" / repo
        if repo_dir.exists():
            self._repos[key] = repo_dir
            return repo_dir

        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        else:
            url = f"https://github.com/{owner}/{repo}.git"

        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        self._run(["git", "clone", "--depth=1", url, str(repo_dir)])
        # Configure git identity for commits
        self._run(["git", "config", "user.email", "mason@stronghold.local"], cwd=repo_dir)
        self._run(["git", "config", "user.name", "Mason"], cwd=repo_dir)
        self._repos[key] = repo_dir
        logger.info("Cloned %s/%s to %s", owner, repo, repo_dir)
        return repo_dir

    def _create(self, args: dict[str, Any]) -> dict[str, str]:
        """Create an isolated worktree for an issue."""
        owner = args.get("owner", "")
        repo = args.get("repo", "")
        issue = args.get("issue_number", 0)
        branch = args.get("branch", f"mason/{issue}")

        repo_dir = self._ensure_clone(owner, repo)
        # Fetch latest main
        self._run(["git", "fetch", "origin", "main"], cwd=repo_dir)

        worktree_dir = self._base / "worktrees" / f"mason-{issue}"
        if worktree_dir.exists():
            return {
                "status": "exists",
                "path": str(worktree_dir),
                "branch": branch,
            }

        self._run(
            ["git", "worktree", "add", str(worktree_dir), "-b", branch, "origin/main"],
            cwd=repo_dir,
        )
        # Don't pip install in the worktree — it would overwrite the running
        # container's stronghold package. Tests run against the worktree's
        # source via PYTHONPATH or by running pytest from the worktree dir.
        logger.info("Created worktree %s on branch %s", worktree_dir, branch)
        return {
            "status": "created",
            "path": str(worktree_dir),
            "branch": branch,
        }

    def _status(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get status of a worktree."""
        issue = args.get("issue_number", 0)
        worktree_dir = self._base / "worktrees" / f"mason-{issue}"
        if not worktree_dir.exists():
            return {"status": "not_found"}
        result = self._run(["git", "status", "--porcelain"], cwd=worktree_dir)
        branch = self._run(["git", "branch", "--show-current"], cwd=worktree_dir).strip()
        return {
            "status": "active",
            "path": str(worktree_dir),
            "branch": branch,
            "changes": result.strip().split("\n") if result.strip() else [],
        }

    def _commit(self, args: dict[str, Any]) -> dict[str, str]:
        """Stage all changes and commit."""
        issue = args.get("issue_number", 0)
        message = args.get("message", f"mason: work on issue #{issue}")
        worktree_dir = self._base / "worktrees" / f"mason-{issue}"
        if not worktree_dir.exists():
            return {"status": "error", "error": "worktree not found"}
        self._run(["git", "add", "-A"], cwd=worktree_dir)
        self._run(["git", "commit", "-m", message, "--allow-empty"], cwd=worktree_dir)
        sha = self._run(["git", "rev-parse", "HEAD"], cwd=worktree_dir).strip()
        return {"status": "committed", "sha": sha}

    def _push(self, args: dict[str, Any]) -> dict[str, str]:
        """Push the worktree branch to origin."""
        issue = args.get("issue_number", 0)
        worktree_dir = self._base / "worktrees" / f"mason-{issue}"
        if not worktree_dir.exists():
            return {"status": "error", "error": "worktree not found"}
        branch = self._run(["git", "branch", "--show-current"], cwd=worktree_dir).strip()
        self._run(["git", "push", "-u", "origin", branch], cwd=worktree_dir)
        return {"status": "pushed", "branch": branch}

    def _cleanup(self, args: dict[str, Any]) -> dict[str, str]:
        """Remove a worktree."""
        issue = args.get("issue_number", 0)
        worktree_dir = self._base / "worktrees" / f"mason-{issue}"
        if not worktree_dir.exists():
            return {"status": "not_found"}
        # Find the parent repo to run worktree remove
        for repo_dir in self._repos.values():
            try:
                self._run(
                    ["git", "worktree", "remove", str(worktree_dir), "--force"],
                    cwd=repo_dir,
                )
                break
            except Exception:
                continue
        # Fallback: just delete the directory
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir)
        return {"status": "cleaned"}

    @staticmethod
    def _run(cmd: list[str], cwd: Path | None = None) -> str:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"{' '.join(cmd[:3])}: {msg}")
        return result.stdout
