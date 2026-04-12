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


# ── GitHub App bot identities ───────────────────────────────────────
#
# Three bots, each a separate GitHub App installed on Agent-StrongHold:
#
#   gatekeeper — CI triage, PR automation, Auditor reviews, default bot
#   archie     — Archie(tect): issue decomposition, acceptance criteria
#   mason      — Mason: tests, implementation, PR creation
#
# Private keys stored in ~/.conductor-secrets/{name}.pem.
# Installation IDs discovered at startup via env or defaults.

_BOT_REGISTRY: dict[str, dict[str, str]] = {
    "gatekeeper": {
        "app_id": "3354708",
        "installation_id": "123359098",
        "key_path": "~/.conductor-secrets/gatekeeper.pem",
    },
    "archie": {
        "app_id": "3354872",
        "installation_id": "123361328",
        "key_path": "~/.conductor-secrets/archie.pem",
    },
    "mason": {
        "app_id": "3354924",
        "installation_id": "123362160",
        "key_path": "~/.conductor-secrets/mason.pem",
    },
}


def _get_app_installation_token(bot: str = "gatekeeper") -> str:
    """Generate a short-lived installation token for a named bot identity.

    Args:
        bot: One of "gatekeeper", "auditor", "mason". Falls back to
             "gatekeeper" for unknown names.

    Env overrides (take precedence over _BOT_REGISTRY):
        GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID

    Returns empty string if credentials are missing (falls back to PAT).
    """
    try:
        import jwt as pyjwt  # noqa: PLC0415
    except ImportError:
        logger.debug("PyJWT not installed — GitHub App auth unavailable")
        return ""

    import time  # noqa: PLC0415

    reg = _BOT_REGISTRY.get(bot, _BOT_REGISTRY["gatekeeper"])

    app_id = os.environ.get("GITHUB_APP_ID", reg["app_id"])
    key_path = os.environ.get(
        "GITHUB_APP_PRIVATE_KEY_PATH",
        os.path.expanduser(reg["key_path"]),
    )
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", reg["installation_id"])

    if not app_id or not installation_id:
        return ""

    try:
        with open(key_path) as f:
            private_key = f.read()
    except FileNotFoundError:
        logger.debug("GitHub App private key not found at %s", key_path)
        return ""

    now = int(time.time())
    jwt_token = pyjwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": app_id},
        private_key,
        algorithm="RS256",
    )

    try:
        import httpx  # noqa: PLC0415

        resp = httpx.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        token = resp.json().get("token", "")
        if token:
            logger.info("GitHub App token generated for bot=%s", bot)
        return token
    except Exception:
        logger.warning("Failed to generate GitHub App token for bot=%s", bot, exc_info=True)
        return ""


class GitHubToolExecutor:
    """Executes GitHub operations via the REST API.

    Implements the ToolExecutor protocol.

    Auth priority:
    1. GitHub App installation token (posts as the named bot)
    2. Explicit token param
    3. GITHUB_TOKEN env var (PAT — posts as the user)

    Pass bot="mason" or bot="archie" to __init__ to select identity.
    Default is "gatekeeper" (CI/triage/Auditor bot).
    """

    def __init__(self, token: str = "", bot: str = "gatekeeper") -> None:
        # Prefer App installation token so actions show as the bot, not the user
        app_token = _get_app_installation_token(bot)
        self._token = app_token or token or os.environ.get("GITHUB_TOKEN", "")
        self._bot = bot
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
        params: dict[str, str] = {
            "state": args.get("state", "open"),
            "per_page": str(args.get("per_page", 100)),
        }
        labels = args.get("labels")
        if labels:
            params["labels"] = ",".join(labels)

        all_issues: list[dict[str, Any]] = []
        page = 1
        max_pages = int(args.get("max_pages", 5))

        async with httpx.AsyncClient(timeout=30.0) as client:
            while page <= max_pages:
                params["page"] = str(page)
                resp = await client.get(
                    f"{self._base_url}/repos/{owner}/{repo}/issues",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                for i in batch:
                    is_pr = "pull_request" in i
                    all_issues.append(
                        {
                            "number": i["number"],
                            "title": i["title"],
                            "state": i["state"],
                            "labels": [lb["name"] for lb in i.get("labels", [])],
                            "assignee": (i.get("assignee") or {}).get("login"),
                            "is_pr": is_pr,
                            "created_at": i.get("created_at", ""),
                        }
                    )
                if len(batch) < int(params["per_page"]):
                    break
                page += 1

        return all_issues

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

    async def _create_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx  # noqa: PLC0415

        owner, repo = args["owner"], args["repo"]
        body: dict[str, Any] = {
            "title": args.get("title", ""),
            "body": args.get("body", ""),
        }
        labels = args.get("labels")
        if labels:
            body["labels"] = labels

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/issues",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            issue = resp.json()
            return {
                "number": issue["number"],
                "url": issue["html_url"],
                "state": issue["state"],
            }

    _handlers: dict[str, Any] = {
        "list_issues": _list_issues,
        "get_issue": _get_issue,
        "create_issue": _create_issue,
        "create_branch": _create_branch,
        "create_pr": _create_pr,
        "get_pr_diff": _get_pr_diff,
        "post_pr_comment": _post_pr_comment,
        "list_pr_comments": _list_pr_comments,
    }
