"""Deprecated shim: translates github(action=…) calls to playbook calls.

Lets existing callers (`api/routes/mason.py`, integration tests) keep
working while the internal migration to playbooks happens. Emits a
DeprecationWarning + INFO log every call so we can track remaining users
and retire the shim in a follow-up sprint.

DO NOT add new callers. If a use case is missing from the playbook set,
add it there — not here.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from stronghold.playbooks.github.list_repo_activity import list_repo_activity
from stronghold.playbooks.github.open_pull_request import open_pull_request
from stronghold.playbooks.github.respond_to_issue import respond_to_issue
from stronghold.playbooks.github.review_pull_request import review_pull_request
from stronghold.playbooks.github.triage_issues import triage_issues
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.tool import ToolResult

logger = logging.getLogger("stronghold.tools.github_shim")


class GithubActionShim:
    """Maps old `github(action=...)` argument shapes to playbooks.

    Supports the subset of actions that have a direct playbook analogue.
    Unknown actions fall through to the legacy GitHubToolExecutor via
    the caller-supplied `fallback` (so nothing breaks mid-migration).
    """

    def __init__(self, fallback: Any | None = None) -> None:
        self._fallback = fallback

    @property
    def name(self) -> str:
        return "github"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        warnings.warn(
            f"github(action={action!r}) is deprecated; use a playbook instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.info("github-shim action=%s", action)

        ctx = PlaybookContext(auth=SYSTEM_AUTH)
        try:
            if action in ("list_issues", "search_issues"):
                repo = f"{arguments['owner']}/{arguments['repo']}"
                query = arguments.get("query", "")
                if not query:
                    state = arguments.get("state", "open")
                    query = f"state:{state}"
                    if arguments.get("labels"):
                        query += " " + " ".join(f"label:{lb}" for lb in arguments["labels"])
                brief = await triage_issues({"repo": repo, "query": query}, ctx)
                return ToolResult(content=brief.to_markdown(), success=True)
            if action == "create_pr":
                owner = arguments["owner"]
                repo = arguments["repo"]
                brief = await open_pull_request(
                    {
                        "repo": f"{owner}/{repo}",
                        "branch": arguments["branch"],
                        "title": arguments.get("title", ""),
                        "body": arguments.get("body", ""),
                        "base": arguments.get("base", "main"),
                    },
                    ctx,
                )
                return ToolResult(content=brief.to_markdown(), success=True)
            if action == "post_pr_comment":
                owner = arguments["owner"]
                repo = arguments["repo"]
                number = arguments["issue_number"]
                url = f"https://github.com/{owner}/{repo}/issues/{number}"
                brief = await respond_to_issue(
                    {
                        "url": url,
                        "action": "comment",
                        "message": arguments.get("body", ""),
                    },
                    ctx,
                )
                return ToolResult(content=brief.to_markdown(), success=True)
            if action == "get_pr_diff":
                owner = arguments["owner"]
                repo = arguments["repo"]
                number = arguments["issue_number"]
                url = f"https://github.com/{owner}/{repo}/pull/{number}"
                brief = await review_pull_request({"url": url}, ctx)
                return ToolResult(content=brief.to_markdown(), success=True)
            if action == "list_repo_activity":
                brief = await list_repo_activity(
                    {
                        "repo": f"{arguments['owner']}/{arguments['repo']}",
                        "kind": arguments.get("kind", "all"),
                    },
                    ctx,
                )
                return ToolResult(content=brief.to_markdown(), success=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("github-shim failed for action=%s: %s", action, exc)
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")

        if self._fallback is not None:
            logger.info("github-shim falling through to legacy executor for action=%s", action)
            fallback_result: ToolResult = await self._fallback.execute(arguments)
            return fallback_result
        return ToolResult(
            success=False,
            error=(
                f"github(action={action!r}) has no playbook mapping and no fallback "
                "is configured. Migrate the caller to the appropriate playbook."
            ),
        )
