"""Mason management API + GitHub webhook receiver.

Endpoints:
- POST /v1/stronghold/mason/assign — assign an issue to Mason
- GET  /v1/stronghold/mason/queue  — list queued issues
- GET  /v1/stronghold/mason/status — current execution status
- POST /v1/stronghold/webhooks/github — GitHub webhook receiver
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from stronghold.agents.mason.queue import InMemoryMasonQueue
    from stronghold.events import Reactor

logger = logging.getLogger("stronghold.api.mason")


def create_mason_routes(
    queue: InMemoryMasonQueue,
    reactor: Reactor,
) -> list[tuple[str, str, Any]]:
    """Create Mason management route handlers.

    Returns list of (path, method, handler) tuples for registration.
    """

    async def assign_issue(request: Request) -> JSONResponse:
        """Assign an issue to Mason's queue."""
        body = await request.json()
        issue_number = body.get("issue_number")
        if not issue_number:
            return JSONResponse({"error": "issue_number is required"}, status_code=400)

        issue = queue.assign(
            issue_number=issue_number,
            title=body.get("title", ""),
            owner=body.get("owner", ""),
            repo=body.get("repo", ""),
        )

        # Emit event so the Reactor watcher picks it up
        from stronghold.types.reactor import Event as EventType

        reactor.emit(
            EventType(
                name="mason.issue_assigned",
                data={
                    "issue_number": issue.issue_number,
                    "title": issue.title,
                },
            )
        )

        return JSONResponse(
            {
                "status": "assigned",
                "issue_number": issue.issue_number,
                "queue_position": sum(1 for i in queue.list_all() if i["status"] == "queued"),
            }
        )

    async def get_queue(request: Request) -> JSONResponse:
        """List all issues in the queue."""
        return JSONResponse({"issues": queue.list_all()})

    async def get_status(request: Request) -> JSONResponse:
        """Get Mason's current execution status."""
        return JSONResponse(queue.status())

    async def github_webhook(request: Request) -> JSONResponse:
        """Receive GitHub webhook events.

        Verifies HMAC-SHA256 signature, then emits Reactor events
        for relevant GitHub actions (issue assigned, PR opened, etc.).
        """
        # Verify webhook signature
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        if secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            body_bytes = await request.body()
            if not _verify_signature(body_bytes, secret, signature):
                return JSONResponse({"error": "Invalid signature"}, status_code=401)
            payload = _parse_json(body_bytes)
        else:
            payload = await request.json()

        event_type = request.headers.get("X-GitHub-Event", "")
        action = payload.get("action", "")

        from stronghold.types.reactor import Event as EventType

        # Issue assigned → queue for Mason
        if event_type == "issues" and action == "assigned":
            issue = payload.get("issue", {})
            repo = payload.get("repository", {})
            queued = queue.assign(
                issue_number=issue.get("number", 0),
                title=issue.get("title", ""),
                owner=repo.get("owner", {}).get("login", ""),
                repo=repo.get("name", ""),
            )
            reactor.emit(
                EventType(
                    name="mason.issue_assigned",
                    data={
                        "issue_number": queued.issue_number,
                        "title": queued.title,
                        "source": "github_webhook",
                    },
                )
            )
            logger.info(
                "Webhook: issue #%d assigned to Mason",
                queued.issue_number,
            )

        # PR opened → trigger Auditor review
        elif event_type == "pull_request" and action == "opened":
            pr = payload.get("pull_request", {})
            reactor.emit(
                EventType(
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

        # PR review submitted → trigger RLHF feedback
        elif event_type == "pull_request_review" and action == "submitted":
            pr = payload.get("pull_request", {})
            review = payload.get("review", {})
            reactor.emit(
                EventType(
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

        return JSONResponse({"status": "ok"})

    return [
        ("/v1/stronghold/mason/assign", "POST", assign_issue),
        ("/v1/stronghold/mason/queue", "GET", get_queue),
        ("/v1/stronghold/mason/status", "GET", get_status),
        ("/v1/stronghold/webhooks/github", "POST", github_webhook),
    ]


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


def _parse_json(body: bytes) -> dict[str, Any]:
    """Parse JSON body bytes."""
    import json

    return json.loads(body)  # type: ignore[no-any-return]
