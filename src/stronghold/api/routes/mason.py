"""Mason management API + GitHub webhook receiver.

Endpoints:
- POST /v1/stronghold/mason/assign      — assign an issue to Mason
- POST /v1/stronghold/mason/review-pr   — request Mason review + improve a PR
- GET  /v1/stronghold/mason/queue       — list queued issues
- GET  /v1/stronghold/mason/status      — current execution status
- POST /v1/stronghold/webhooks/github   — GitHub webhook receiver
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.mason")

router = APIRouter(tags=["mason"])


def configure_mason_router(
    queue: Any,
    reactor: Any,
    container: Any = None,
) -> None:
    """Bind the Mason queue, reactor, and container to the router."""
    _state["queue"] = queue
    _state["reactor"] = reactor
    _state["container"] = container


# Module-level state — set by configure_mason_router at startup
_state: dict[str, Any] = {}


def _queue() -> Any:
    return _state["queue"]


def _reactor() -> Any:
    return _state["reactor"]


@router.post("/v1/stronghold/mason/assign")
async def assign_issue(request: Request) -> JSONResponse:
    """Assign a GitHub issue to Mason's queue."""
    body = await request.json()
    issue_number = body.get("issue_number")
    if not issue_number:
        return JSONResponse({"error": "issue_number is required"}, status_code=400)

    queue = _queue()
    issue = queue.assign(
        issue_number=issue_number,
        title=body.get("title", ""),
        owner=body.get("owner", ""),
        repo=body.get("repo", ""),
    )

    import asyncio

    # Dispatch Mason in the background
    asyncio.create_task(_dispatch_mason(issue))

    return JSONResponse(
        {
            "status": "assigned",
            "issue_number": issue.issue_number,
            "queue_position": sum(1 for i in queue.list_all() if i["status"] == "queued"),
        }
    )


async def _dispatch_mason(issue: Any) -> None:
    """Background task: Frank plans, then Mason builds."""
    from stronghold.types.auth import SYSTEM_AUTH

    queue = _queue()
    issue_num = issue.issue_number
    queue.start(issue_num)

    try:
        container = _state.get("container")
        if not container:
            queue.fail(issue_num, error="container not available")
            return

        async def _log(msg: str) -> None:
            queue.add_log(issue_num, msg)

        # Create workspace
        from stronghold.tools.workspace import WorkspaceManager

        ws = WorkspaceManager()
        await _log("Creating workspace")
        ws_result = await ws.execute(
            {
                "action": "create",
                "issue_number": issue_num,
                "owner": issue.owner,
                "repo": issue.repo,
            }
        )
        if not ws_result.success:
            queue.fail(issue_num, error=f"workspace: {ws_result.error}")
            return

        import json as _json

        ws_data = _json.loads(ws_result.content)
        ws_path = ws_data["path"]
        branch = ws_data["branch"]
        await _log(f"Workspace: {branch}")

        await container.route_request(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Implement GitHub issue #{issue_num}: {issue.title}\n"
                        f"Repository: {issue.owner}/{issue.repo}\n"
                        f"Branch: {branch}\n"
                        f"Workspace: {ws_path}"
                    ),
                }
            ],
            auth=SYSTEM_AUTH,
            intent_hint="code_gen",
            status_callback=_log,
        )
        queue.complete(issue_num)
    except Exception as e:
        queue.add_log(issue_num, f"Failed: {e}")
        queue.fail(issue_num, error=str(e))


@router.post("/v1/stronghold/mason/review-pr")
async def review_pr(request: Request) -> JSONResponse:
    """Request Mason to review and improve an existing PR.

    Mason reads the diff, existing comments, and its stored learnings,
    then pushes improvements addressing the feedback.
    """
    body = await request.json()
    pr_number = body.get("pr_number")
    if not pr_number:
        return JSONResponse({"error": "pr_number is required"}, status_code=400)

    from stronghold.types.reactor import Event

    _reactor().emit(
        Event(
            name="mason.pr_review_requested",
            data={
                "pr_number": pr_number,
                "owner": body.get("owner", ""),
                "repo": body.get("repo", ""),
                "mode": "review_and_improve",
            },
        )
    )

    return JSONResponse(
        {
            "status": "queued",
            "pr_number": pr_number,
            "mode": "review_and_improve",
        }
    )


@router.get("/v1/stronghold/mason/queue")
async def get_queue() -> JSONResponse:
    """List all issues in Mason's queue."""
    return JSONResponse({"issues": _queue().list_all()})


@router.get("/v1/stronghold/mason/status")
async def get_status() -> JSONResponse:
    """Get Mason's current execution status."""
    return JSONResponse(_queue().status())


# Server-side cache: 15min TTL when populated, 1min when empty
_issues_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
_CACHE_TTL_FULL = 900.0  # 15 minutes
_CACHE_TTL_EMPTY = 60.0  # 1 minute


async def _fetch_github_items(owner: str, repo: str) -> dict[str, Any]:
    """Fetch from GitHub or return cached data."""
    import json as _json
    import time

    from stronghold.tools.github import GitHubToolExecutor

    cache_key = f"{owner}/{repo}"
    now = time.monotonic()
    cached = _issues_cache.get("data")
    cached_key = _issues_cache.get("key", "")
    fetched_at = _issues_cache.get("fetched_at", 0.0)

    if cached is not None and cached_key == cache_key:
        is_empty = cached.get("total", 0) == 0
        ttl = _CACHE_TTL_EMPTY if is_empty else _CACHE_TTL_FULL
        if now - fetched_at < ttl:
            return cast("dict[str, Any]", cached)

    github = GitHubToolExecutor()
    result = await github.execute(
        {
            "action": "list_issues",
            "owner": owner,
            "repo": repo,
            "state": "open",
            "per_page": 100,
            "max_pages": 5,
        }
    )
    if not result.success:
        # Return stale cache if fetch fails
        if cached is not None and cached_key == cache_key:
            return cast("dict[str, Any]", cached)
        return {"error": result.error}

    items = _json.loads(result.content)
    all_labels: set[str] = set()
    for item in items:
        for label in item.get("labels", []):
            all_labels.add(label)

    data: dict[str, Any] = {
        "items": items,
        "total": len(items),
        "labels": sorted(all_labels),
    }
    _issues_cache["data"] = data
    _issues_cache["key"] = cache_key
    _issues_cache["fetched_at"] = now
    return data


@router.get("/v1/stronghold/mason/issues")
async def list_github_issues(request: Request) -> JSONResponse:
    """Fetch all open issues and PRs. Cached: 15min full, 1min empty."""
    owner = request.query_params.get("owner", "")
    repo = request.query_params.get("repo", "")
    if not owner or not repo:
        return JSONResponse({"error": "owner and repo query params required"}, status_code=400)

    data = await _fetch_github_items(owner, repo)
    if "error" in data:
        return JSONResponse({"error": data["error"]}, status_code=502)

    return JSONResponse(data)


@router.get("/v1/stronghold/mason/scan")
async def scan_codebase() -> JSONResponse:
    """Scan codebase for good-first-issue opportunities.

    Returns suggestions for approachable tasks that teach
    new contributors about the architecture.
    """
    from pathlib import Path

    from stronghold.tools.scanner import (
        format_as_github_issue,
        scan_for_good_first_issues,
    )

    # Try repo root (dev), fall back to /app (container)
    candidate = Path(__file__).resolve().parents[4]
    project_root = candidate if (candidate / "tests").is_dir() else Path("/app")
    suggestions = scan_for_good_first_issues(project_root)
    return JSONResponse(
        {
            "count": len(suggestions),
            "suggestions": [
                {
                    "title": s.title,
                    "category": s.category,
                    "scope": s.estimated_scope,
                    "files": list(s.files),
                    "what_youll_learn": s.what_youll_learn,
                    "github_payload": format_as_github_issue(s),
                }
                for s in suggestions
            ],
        }
    )


@router.post("/v1/stronghold/mason/scan/create")
async def create_scanned_issues(request: Request) -> JSONResponse:
    """Create GitHub issues from scan results via GitHub API.

    Body: {"indices": [0, 1, 2], "owner": "org", "repo": "repo"}
    Or: {"all": true, "owner": "org", "repo": "repo"}
    """
    from pathlib import Path

    from stronghold.tools.github import GitHubToolExecutor
    from stronghold.tools.scanner import (
        format_as_github_issue,
        scan_for_good_first_issues,
    )

    body = await request.json()
    owner = body.get("owner", "")
    repo = body.get("repo", "")
    if not owner or not repo:
        return JSONResponse({"error": "owner and repo are required"}, status_code=400)

    candidate = Path(__file__).resolve().parents[4]
    project_root = candidate if (candidate / "tests").is_dir() else Path("/app")
    suggestions = scan_for_good_first_issues(project_root)

    indices: list[int] = body.get("indices", [])
    if body.get("all"):
        indices = list(range(len(suggestions)))

    github = GitHubToolExecutor()
    created: list[dict[str, object]] = []
    errors: list[str] = []

    for idx in indices:
        if not (0 <= idx < len(suggestions)):
            continue
        payload = format_as_github_issue(suggestions[idx])
        result = await github.execute(
            {
                "action": "create_issue",
                "owner": owner,
                "repo": repo,
                "title": payload["title"],
                "body": str(payload["body"]),
                "labels": payload.get("labels", []),
            }
        )
        if result.success:
            created.append({"title": payload["title"], "result": result.content})
        else:
            errors.append(f"{payload['title']}: {result.error}")

    return JSONResponse(
        {
            "created": len(created),
            "errors": errors,
            "issues": created,
        }
    )


@router.post("/v1/stronghold/webhooks/github")
async def github_webhook(request: Request) -> JSONResponse:
    """Receive GitHub webhook events.

    Verifies HMAC-SHA256 signature, then emits Reactor events
    for relevant GitHub actions.
    """
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        body_bytes = await request.body()
        if not _verify_signature(body_bytes, secret, signature):
            return JSONResponse({"error": "Invalid signature"}, status_code=401)
        payload: dict[str, Any] = json.loads(body_bytes)
    else:
        payload = await request.json()

    event_type = request.headers.get("X-GitHub-Event", "")
    action = payload.get("action", "")

    from stronghold.types.reactor import Event

    # Issue assigned -> queue for Mason
    if event_type == "issues" and action in ("assigned", "labeled"):
        issue = payload.get("issue", {})
        issue_labels = {label["name"] for label in issue.get("labels", [])}

        # Only react to issues with the `builders` label
        if "builders" not in issue_labels:
            logger.debug("Webhook: issue #%d has no builders label, ignoring", issue.get("number"))
        else:
            # The backlog scanner (runs every 5 min) will pick this up.
            # We just log it here — no direct dispatch to Mason.
            logger.info(
                "Webhook: issue #%d labeled builders — will be picked up by backlog scanner",
                issue.get("number", 0),
            )

    # PR opened -> trigger Auditor review
    elif event_type == "pull_request" and action == "opened":
        pr = payload.get("pull_request", {})
        _reactor().emit(
            Event(
                name="pr.opened",
                data={
                    "pr_number": pr.get("number", 0),
                    "title": pr.get("title", ""),
                    "author": pr.get("user", {}).get("login", ""),
                    "source": "github_webhook",
                },
            )
        )
        logger.info("Webhook: PR #%d opened", pr.get("number", 0))

    # PR review comment -> RLHF feedback extraction
    elif event_type == "pull_request_review" and action == "submitted":
        pr = payload.get("pull_request", {})
        review = payload.get("review", {})
        _reactor().emit(
            Event(
                name="pr.reviewed",
                data={
                    "pr_number": pr.get("number", 0),
                    "review_state": review.get("state", ""),
                    "reviewer": review.get("user", {}).get("login", ""),
                    "body": review.get("body", ""),
                    "source": "github_webhook",
                },
            )
        )

    # Issue comment -> Mason can learn from human feedback
    elif event_type == "issue_comment" and action == "created":
        comment = payload.get("comment", {})
        issue = payload.get("issue", {})
        # Only process comments on PRs (issues with pull_request key)
        if "pull_request" in issue:
            _reactor().emit(
                Event(
                    name="pr.commented",
                    data={
                        "pr_number": issue.get("number", 0),
                        "commenter": comment.get("user", {}).get("login", ""),
                        "body": comment.get("body", ""),
                        "source": "github_webhook",
                    },
                )
            )

    return JSONResponse({"status": "ok"})


def _verify_signature(body: bytes, secret: str, signature: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
