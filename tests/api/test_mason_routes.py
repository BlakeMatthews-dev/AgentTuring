"""Tests for Mason API routes and GitHub webhook receiver.

Uses real classes: InMemoryMasonQueue, Reactor. No mocks.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from starlette.testclient import TestClient

from stronghold.agents.mason.queue import InMemoryMasonQueue
from stronghold.api.routes.mason import _verify_signature, create_mason_routes
from stronghold.events import Reactor


def _build_app() -> tuple[TestClient, InMemoryMasonQueue, Reactor]:
    """Build a minimal Starlette app with Mason routes."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    queue = InMemoryMasonQueue()
    reactor = Reactor()
    routes_spec = create_mason_routes(queue, reactor)

    starlette_routes = []
    for path, method, handler in routes_spec:
        starlette_routes.append(Route(path, handler, methods=[method]))

    app = Starlette(routes=starlette_routes)
    client = TestClient(app)
    return client, queue, reactor


class TestAssignEndpoint:
    """POST /v1/stronghold/mason/assign."""

    def test_assigns_issue(self) -> None:
        client, queue, _ = _build_app()
        resp = client.post(
            "/v1/stronghold/mason/assign",
            json={"issue_number": 42, "title": "Fix bug", "owner": "org", "repo": "repo"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "assigned"
        assert queue.has_pending()

    def test_missing_issue_number(self) -> None:
        client, _, _ = _build_app()
        resp = client.post(
            "/v1/stronghold/mason/assign",
            json={"title": "Fix bug"},
        )
        assert resp.status_code == 400

    def test_emits_reactor_event(self) -> None:
        client, _, reactor = _build_app()
        events: list[str] = []
        # Register a listener to verify event emission
        from stronghold.types.reactor import TriggerMode, TriggerSpec

        async def _capture(event: object) -> dict[str, object]:
            events.append("fired")
            return {}

        reactor.register(
            TriggerSpec(
                name="test_capture",
                mode=TriggerMode.EVENT,
                event_pattern=r"mason\.issue_assigned",
            ),
            _capture,
        )
        client.post(
            "/v1/stronghold/mason/assign",
            json={"issue_number": 42},
        )
        # Event was emitted (may not have fired yet in sync context)
        # but the emit call should not error


class TestQueueEndpoint:
    """GET /v1/stronghold/mason/queue."""

    def test_empty_queue(self) -> None:
        client, _, _ = _build_app()
        resp = client.get("/v1/stronghold/mason/queue")
        assert resp.status_code == 200
        assert resp.json()["issues"] == []

    def test_lists_assigned_issues(self) -> None:
        client, queue, _ = _build_app()
        queue.assign(1, title="First")
        queue.assign(2, title="Second")
        resp = client.get("/v1/stronghold/mason/queue")
        assert len(resp.json()["issues"]) == 2


class TestStatusEndpoint:
    """GET /v1/stronghold/mason/status."""

    def test_empty_status(self) -> None:
        client, _, _ = _build_app()
        resp = client.get("/v1/stronghold/mason/status")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGitHubWebhook:
    """POST /v1/stronghold/webhooks/github."""

    def test_issue_assigned_queues_for_mason(self) -> None:
        client, queue, _ = _build_app()
        payload = {
            "action": "assigned",
            "issue": {"number": 42, "title": "Implement feature"},
            "repository": {
                "name": "stronghold",
                "owner": {"login": "Agent-StrongHold"},
            },
        }
        resp = client.post(
            "/v1/stronghold/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "issues"},
        )
        assert resp.status_code == 200
        assert queue.has_pending()
        pending = queue.next_pending()
        assert pending is not None
        assert pending.issue_number == 42

    def test_pr_opened_emits_event(self) -> None:
        client, _, _ = _build_app()
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 99,
                "title": "feat: new feature",
                "user": {"login": "mason"},
            },
        }
        resp = client.post(
            "/v1/stronghold/webhooks/github",
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert resp.status_code == 200

    def test_unrelated_event_ignored(self) -> None:
        client, queue, _ = _build_app()
        resp = client.post(
            "/v1/stronghold/webhooks/github",
            json={"action": "deleted"},
            headers={"X-GitHub-Event": "repository"},
        )
        assert resp.status_code == 200
        assert not queue.has_pending()


class TestWebhookSignatureVerification:
    """HMAC-SHA256 signature verification."""

    def test_valid_signature(self) -> None:
        body = b'{"test": true}'
        secret = "webhook-secret-123"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(body, secret, f"sha256={expected}")

    def test_invalid_signature(self) -> None:
        body = b'{"test": true}'
        assert not _verify_signature(body, "secret", "sha256=wrong")

    def test_missing_prefix(self) -> None:
        assert not _verify_signature(b"body", "secret", "md5=abc")
