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
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.workspace")

DEFAULT_WORKSPACE_ROOT = Path(os.environ.get("STRONGHOLD_WORKSPACE", "/workspace"))

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


def _sanitize_secrets(text: str) -> str:
    """Remove known secret patterns from text to prevent leaking in error messages."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and token in text:
        text = text.replace(token, "***")
    # Also strip any x-access-token:TOKEN@ patterns (legacy or third-party)
    text = re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", text)
    # Strip Authorization: Bearer <token> patterns
    text = re.sub(r"Authorization: Bearer \S+", "Authorization: Bearer ***", text)
    return text


class WorkspaceManager:
    """Manages git repos and worktrees for Mason."""

    def __init__(self) -> None:
        self._base = self._resolve_base_dir()
        self._repos: dict[str, Path] = {}

    @property
    def name(self) -> str:
        return "workspace"

    @staticmethod
    def _resolve_base_dir() -> Path:
        """Prefer configured root, but fall back to a writable temp location."""
        candidates = [
            DEFAULT_WORKSPACE_ROOT,
            Path(tempfile.gettempdir()) / "stronghold-workspace",
        ]
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                logger.warning("Workspace root unavailable: %s", candidate)
        msg = "No writable workspace root available"
        raise RuntimeError(msg)

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
        """Clone the repo if not already cloned.

        Uses git config http.extraHeader for authentication instead of
        embedding tokens in the clone URL. URL-embedded tokens leak to
        ps output, /proc/*/cmdline, git error messages, and .git/config.
        """
        key = f"{owner}/{repo}"
        if key in self._repos:
            return self._repos[key]

        repo_dir = self._base / "repos" / repo
        if repo_dir.exists():
            self._repos[key] = repo_dir
            return repo_dir

        url = f"https://github.com/{owner}/{repo}.git"
        token = os.environ.get("GITHUB_TOKEN", "")

        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        # Clone with auth header (not URL-embedded token) to avoid leaking
        # secrets in process listings, error messages, and .git/config.
        clone_cmd = ["git", "clone", "--depth=1"]
        if token:
            clone_cmd += [
                "-c",
                f"http.https://github.com/.extraheader=Authorization: Bearer {token}",
            ]
        clone_cmd += [url, str(repo_dir)]
        self._run(clone_cmd)

        # Configure git identity for commits
        self._run(["git", "config", "user.email", "mason@stronghold.local"], cwd=repo_dir)
        self._run(["git", "config", "user.name", "Mason"], cwd=repo_dir)
        # Persist auth for future fetches/pushes in this repo
        if token:
            self._run(
                [
                    "git",
                    "config",
                    "http.https://github.com/.extraheader",
                    f"Authorization: Bearer {token}",
                ],
                cwd=repo_dir,
            )
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
            # Sanitize any tokens from error messages to prevent leaks
            msg = _sanitize_secrets(msg)
            raise RuntimeError(f"{' '.join(cmd[:3])}: {msg}")
        return result.stdout
