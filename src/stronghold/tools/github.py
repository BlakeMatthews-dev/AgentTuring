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
        "create PRs, get PR diffs, post/read PR comments, list issue comment, "
        "search issues, get linked issues."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_issues",
                    "get_issue",
                    "create_issue",
                    "create_branch",
                    "create_pr",
                    "get_pr_diff",
                    "post_pr_comment",
                    "edit_comment",
                    "list_pr_comments",
                    "list_issue_comments",
                    "search_issues",
                    "get_linked_issues",
                    "create_sub_issue",
                    "list_sub_issues",
                    "get_parent_issue",
                    "add_blocked_by",
                    "list_blocked_by",
                    "list_blocking",
                    "review_pr",
                    "merge_pr",
                    "list_pr_files",
                    "get_check_runs",
                    "get_pr",
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
            "query": {"type": "string", "description": "Search query for search_issues action."},
            "sub_issue_id": {
                "type": "integer",
                "description": "Issue ID (not number) to add as a sub-issue.",
            },
            "blocker_issue_id": {
                "type": "integer",
                "description": "Issue ID (not number) that is blocking this one.",
            },
            "comment_id": {
                "type": "integer",
                "description": "Comment ID for edit_comment action.",
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
        import httpx

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
        import httpx

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
                "title": issue.get("title", ""),
                "body": issue.get("body", ""),
                "state": issue.get("state", ""),
                "labels": [lb["name"] for lb in issue.get("labels", [])],
                "assignee": (issue.get("assignee") or {}).get("login"),
            }

    async def _create_branch(self, args: dict[str, Any]) -> dict[str, str]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        branch = args["branch"]
        base = args.get("base", "main")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/git/ref/heads/{base}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            sha = resp.json()["object"]["sha"]

            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/git/refs",
                headers=self._headers(),
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            resp.raise_for_status()
            return {"branch": branch, "sha": sha, "status": "created"}

    async def _create_pr(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/pulls",
                headers=self._headers(),
                json={
                    "title": args.get("title", ""),
                    "body": args.get("body", ""),
                    "head": args.get("head", args.get("branch", "")),
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
        import httpx

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
        import httpx

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

    async def _edit_comment(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        comment_id = args["comment_id"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(
                f"{self._base_url}/repos/{owner}/{repo}/issues/comments/{comment_id}",
                headers=self._headers(),
                json={"body": args.get("body", "")},
            )
            resp.raise_for_status()
            comment = resp.json()
            return {"id": comment["id"], "url": comment["html_url"]}

    async def _list_pr_comments(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

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
        import httpx

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

    async def _list_issue_comments(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

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

    async def _search_issues(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        query = args.get("query", "")
        scoped_query = f"repo:{owner}/{repo} {query}"
        params: dict[str, str] = {"q": scoped_query, "per_page": str(args.get("per_page", 30))}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/search/issues",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "total_count": data.get("total_count", 0),
                "items": [
                    {
                        "number": item["number"],
                        "title": item["title"],
                        "state": item["state"],
                        "html_url": item["html_url"],
                        "is_pr": "pull_request" in item,
                    }
                    for item in data.get("items", [])
                ],
            }

    async def _get_linked_issues(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/timeline",
                headers={
                    **self._headers(),
                    "Accept": "application/vnd.github.mockingbird+json",
                },
            )
            resp.raise_for_status()
            events = resp.json()
            linked = []
            link_events = {"connected", "cross-referenced"}
            for event in events:
                event_type = event.get("event", "")
                if event_type not in link_events:
                    continue
                source = event.get("source", {})
                if not source:
                    continue
                issue = source.get("issue", {})
                if not issue:
                    continue
                linked.append(
                    {
                        "number": issue["number"],
                        "title": issue.get("title", ""),
                        "state": issue.get("state", ""),
                        "html_url": issue.get("html_url", ""),
                        "is_pr": "pull_request" in issue,
                    }
                )
            return linked

    def _v3_headers(self) -> dict[str, str]:
        """Headers for the 2026-03-10 API version (sub-issues, dependencies)."""
        h = self._headers()
        h["X-GitHub-Api-Version"] = "2026-03-10"
        return h

    async def _create_sub_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        """Add an existing issue as a sub-issue of a parent.

        Requires the GitHub-internal issue ID of the child (not the issue
        number). Pass child issue_number — we'll look up the ID first.
        """
        import httpx

        owner, repo = args["owner"], args["repo"]
        parent = args["issue_number"]
        child_number = args.get("sub_issue_number")
        sub_issue_id = args.get("sub_issue_id")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Resolve child issue_number → internal ID if needed
            if sub_issue_id is None and child_number is not None:
                lookup = await client.get(
                    f"{self._base_url}/repos/{owner}/{repo}/issues/{child_number}",
                    headers=self._headers(),
                )
                lookup.raise_for_status()
                sub_issue_id = lookup.json()["id"]

            if sub_issue_id is None:
                raise ValueError("sub_issue_id or sub_issue_number required")

            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{parent}/sub_issues",
                headers=self._v3_headers(),
                json={"sub_issue_id": int(sub_issue_id)},
            )
            resp.raise_for_status()
            return {"parent": parent, "child_id": sub_issue_id, "status": "linked"}

    async def _list_sub_issues(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/sub_issues",
                headers=self._v3_headers(),
            )
            resp.raise_for_status()
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "state": i["state"],
                    "html_url": i.get("html_url", ""),
                }
                for i in resp.json()
            ]

    async def _get_parent_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/parent",
                headers=self._v3_headers(),
            )
            if resp.status_code == 404:
                return {"parent": None}
            resp.raise_for_status()
            parent = resp.json()
            return {
                "parent": {
                    "number": parent["number"],
                    "title": parent.get("title", ""),
                    "state": parent.get("state", ""),
                    "html_url": parent.get("html_url", ""),
                },
            }

    async def _add_blocked_by(self, args: dict[str, Any]) -> dict[str, Any]:
        """Mark issue {issue_number} as blocked by another issue.

        Accepts blocker_issue_id (internal ID) OR blocker_issue_number
        (we'll look up the ID).
        """
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        blocker_id = args.get("blocker_issue_id")
        blocker_number = args.get("blocker_issue_number")

        async with httpx.AsyncClient(timeout=30.0) as client:
            if blocker_id is None and blocker_number is not None:
                lookup = await client.get(
                    f"{self._base_url}/repos/{owner}/{repo}/issues/{blocker_number}",
                    headers=self._headers(),
                )
                lookup.raise_for_status()
                blocker_id = lookup.json()["id"]

            if blocker_id is None:
                raise ValueError("blocker_issue_id or blocker_issue_number required")

            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by",
                headers=self._v3_headers(),
                json={"issue_id": int(blocker_id)},
            )
            resp.raise_for_status()
            return {"issue": number, "blocker_id": blocker_id, "status": "linked"}

    async def _list_blocked_by(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by",
                headers=self._v3_headers(),
            )
            resp.raise_for_status()
            return [
                {
                    "number": i["number"],
                    "title": i.get("title", ""),
                    "state": i.get("state", ""),
                }
                for i in resp.json()
            ]

    async def _list_blocking(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/dependencies/blocking",
                headers=self._v3_headers(),
            )
            resp.raise_for_status()
            return [
                {
                    "number": i["number"],
                    "title": i.get("title", ""),
                    "state": i.get("state", ""),
                }
                for i in resp.json()
            ]

    async def _get_pr(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/pulls/{number}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            pr = resp.json()
            return {
                "number": pr["number"],
                "title": pr.get("title", ""),
                "body": pr.get("body") or "",
                "state": pr["state"],
                "user": pr.get("user", {}).get("login", ""),
                "head": {
                    "ref": pr["head"]["ref"],
                    "sha": pr["head"]["sha"],
                },
                "base": {
                    "ref": pr["base"]["ref"],
                    "sha": pr["base"]["sha"],
                },
                "mergeable": pr.get("mergeable"),
                "mergeable_state": pr.get("mergeable_state", ""),
                "html_url": pr.get("html_url", ""),
                "draft": pr.get("draft", False),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "changed_files": pr.get("changed_files", 0),
            }

    async def _list_pr_files(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/pulls/{number}/files",
                headers=self._headers(),
                params={"per_page": 100},
            )
            resp.raise_for_status()
            return [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "changes": f["changes"],
                    "patch": f.get("patch", "")[:5000],
                }
                for f in resp.json()
            ]

    async def _review_pr(self, args: dict[str, Any]) -> dict[str, Any]:
        """Submit a review on a PR.

        event: APPROVE | REQUEST_CHANGES | COMMENT

        GitHub rejects APPROVE and REQUEST_CHANGES when the reviewer is also
        the PR author (422). Falls back to a regular issue comment in that
        case so the feedback is still delivered.
        """
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        event = args.get("event", "COMMENT")
        body = args.get("body", "")
        comments = args.get("comments", [])

        payload: dict[str, Any] = {"event": event, "body": body}
        if comments:
            payload["comments"] = comments

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/repos/{owner}/{repo}/pulls/{number}/reviews",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code == 422 and event != "COMMENT":
                # Self-review not allowed — post as issue comment instead
                prefix = f"**[Gatekeeper {event}]**\n\n"
                fallback = await client.post(
                    f"{self._base_url}/repos/{owner}/{repo}/issues/{number}/comments",
                    headers=self._headers(),
                    json={"body": prefix + body},
                )
                fallback.raise_for_status()
                comment = fallback.json()
                return {
                    "id": comment["id"],
                    "state": f"FALLBACK_COMMENT_{event}",
                    "url": comment.get("html_url", ""),
                    "note": "self-review blocked by GitHub, posted as comment",
                }
            resp.raise_for_status()
            review = resp.json()
            return {
                "id": review["id"],
                "state": review["state"],
                "url": review.get("html_url", ""),
            }

    async def _merge_pr(self, args: dict[str, Any]) -> dict[str, Any]:
        """Merge a PR.

        merge_method: merge | squash | rebase
        """
        import httpx

        owner, repo = args["owner"], args["repo"]
        number = args["issue_number"]
        payload: dict[str, Any] = {
            "merge_method": args.get("merge_method", "squash"),
        }
        if "commit_title" in args:
            payload["commit_title"] = args["commit_title"]
        if "commit_message" in args:
            payload["commit_message"] = args["commit_message"]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{self._base_url}/repos/{owner}/{repo}/pulls/{number}/merge",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code == 405:
                return {
                    "merged": False,
                    "message": "Not mergeable (method not allowed)",
                }
            if resp.status_code == 409:
                return {"merged": False, "message": "Head sha mismatch"}
            resp.raise_for_status()
            result = resp.json()
            return {
                "merged": result.get("merged", False),
                "sha": result.get("sha", ""),
                "message": result.get("message", ""),
            }

    async def _get_check_runs(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get check runs for a commit SHA."""
        import httpx

        owner, repo = args["owner"], args["repo"]
        ref = args.get("ref") or args.get("sha", "")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base_url}/repos/{owner}/{repo}/commits/{ref}/check-runs",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "total_count": data.get("total_count", 0),
                "check_runs": [
                    {
                        "name": c["name"],
                        "status": c["status"],
                        "conclusion": c.get("conclusion", ""),
                    }
                    for c in data.get("check_runs", [])
                ],
            }

    _handlers: dict[str, Any] = {
        "list_issues": _list_issues,
        "get_issue": _get_issue,
        "create_issue": _create_issue,
        "create_branch": _create_branch,
        "create_pr": _create_pr,
        "get_pr": _get_pr,
        "get_pr_diff": _get_pr_diff,
        "post_pr_comment": _post_pr_comment,
        "edit_comment": _edit_comment,
        "list_pr_comments": _list_pr_comments,
        "list_pr_files": _list_pr_files,
        "review_pr": _review_pr,
        "merge_pr": _merge_pr,
        "get_check_runs": _get_check_runs,
        "create_sub_issue": _create_sub_issue,
        "list_sub_issues": _list_sub_issues,
        "get_parent_issue": _get_parent_issue,
        "add_blocked_by": _add_blocked_by,
        "list_blocked_by": _list_blocked_by,
        "list_blocking": _list_blocking,
        "list_issue_comments": _list_issue_comments,
        "search_issues": _search_issues,
        "get_linked_issues": _get_linked_issues,
    }
