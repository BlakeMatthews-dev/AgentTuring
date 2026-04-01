"""GitHub tool executor — REST API client for Mason's git operations.

Implements the ToolExecutor protocol. Uses httpx for HTTP (no CLI dependency).
Auth via GITHUB_TOKEN env var (K8s secret compatible).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.github")

GITHUB_TOOL_DEF = ToolDefinition(
    name="github",
    description=(
        "GitHub operations: list issues, get issue details, create branches, "
        "create PRs, get PR diffs, post/read PR comments."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_issues",
                    "get_issue",
                    "create_branch",
                    "create_pr",
                    "get_pr_diff",
                    "post_pr_comment",
                    "list_pr_comments",
                ],
                "description": "The GitHub operation to perform.",
            },
            "owner": {"type": "string", "description": "Repository owner."},
            "repo": {"type": "string", "description": "Repository name."},
            "issue_number": {"type": "integer", "description": "Issue or PR number."},
            "branch": {"type": "string", "description": "Branch name."},
            "base": {"type": "string", "description": "Base branch (default: main)."},
            "title": {"type": "string", "description": "PR title."},
            "body": {"type": "string", "description": "PR body or comment text."},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by labels.",
            },
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "Issue state filter.",
            },
        },
        "required": ["action", "owner", "repo"],
    },
    groups=("code_gen", "review"),
    auth_key_env="GITHUB_TOKEN",
)


class GitHubToolExecutor:
    """Executes GitHub operations via the REST API.

    Implements the ToolExecutor protocol.
    """

    def __init__(self, token: str = "") -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._base_url = "https://api.github.com"

    @property
    def name(self) -> str:
        return "github"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Dispatch to the appropriate GitHub API method."""
        action = arguments.get("action", "")
        try:
            handler = self._handlers.get(action)
            if handler is None:
                return ToolResult(
                    success=False,
                    error=f"Unknown GitHub action: {action}",
                )
            result = await handler(self, arguments)
            return ToolResult(content=json.dumps(result), success=True)
        except Exception as e:
            logger.warning("GitHub tool error (%s): %s", action, e)
            return ToolResult(success=False, error=str(e))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _list_issues(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        params: dict[str, str] = {"state": args.get("state", "open")}
        labels = args.get("labels")
        if labels:
            params["labels"] = ",".join(labels)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            issues = resp.json()
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "state": i["state"],
                    "labels": [lb["name"] for lb in i.get("labels", [])],
                    "assignee": (i.get("assignee") or {}).get("login"),
                }
                for i in issues
                if "pull_request" not in i  # exclude PRs
            ]

    async def _get_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            issue = resp.json()
            return {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body", ""),
                "state": issue["state"],
                "labels": [lb["name"] for lb in issue.get("labels", [])],
                "assignee": (issue.get("assignee") or {}).get("login"),
            }

    async def _create_branch(self, args: dict[str, Any]) -> dict[str, str]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        branch = args["branch"]
        base = args.get("base", "main")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get base branch SHA
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/git/ref/heads/{base}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            sha = resp.json()["object"]["sha"]

            # Create new branch
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/git/refs",
                headers=self._headers(),
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            resp.raise_for_status()
            return {"branch": branch, "sha": sha, "status": "created"}

    async def _create_pr(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/pulls",
                headers=self._headers(),
                json={
                    "title": args.get("title", ""),
                    "body": args.get("body", ""),
                    "head": args["branch"],
                    "base": args.get("base", "main"),
                },
            )
            resp.raise_for_status()
            pr = resp.json()
            return {
                "number": pr["number"],
                "url": pr["html_url"],
                "state": pr["state"],
            }

    async def _get_pr_diff(self, args: dict[str, Any]) -> dict[str, str]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/pulls/{number}",
                headers={**self._headers(), "Accept": "application/vnd.github.diff"},
            )
            resp.raise_for_status()
            return {"diff": resp.text}

    async def _post_pr_comment(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/comments",
                headers=self._headers(),
                json={"body": args.get("body", "")},
            )
            resp.raise_for_status()
            comment = resp.json()
            return {"id": comment["id"], "url": comment["html_url"]}

    async def _list_pr_comments(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/comments",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return [
                {
                    "id": c["id"],
                    "user": c["user"]["login"],
                    "body": c["body"],
                    "created_at": c["created_at"],
                }
                for c in resp.json()
            ]

    _handlers: dict[str, Any] = {
        "list_issues": _list_issues,
        "get_issue": _get_issue,
        "create_branch": _create_branch,
        "create_pr": _create_pr,
        "get_pr_diff": _get_pr_diff,
        "post_pr_comment": _post_pr_comment,
        "list_pr_comments": _list_pr_comments,
    }
