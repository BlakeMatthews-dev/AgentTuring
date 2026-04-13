"""Tests for the Mason management API + GitHub webhook receiver.

Covers all 10 route handlers and 2 internal functions in
src/stronghold/api/routes/mason.py (193 stmts, 0% → target 100%).

Uses httpx.AsyncClient with ASGI transport against a minimal FastAPI
app — no live server, no network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from stronghold.api.routes.mason import (
    _issues_cache,
    _verify_signature,
    configure_mason_router,
    router,
)
from stronghold.security.auth_static import StaticKeyAuthProvider

_AUTH_HEADERS = {"Authorization": "Bearer sk-test"}


# ---------------------------------------------------------------------------
# Fake queue (minimal MasonQueue stand-in)
# ---------------------------------------------------------------------------


class _FakeIssue:
    def __init__(self, issue_number: int, title: str = "", owner: str = "", repo: str = "") -> None:
        self.issue_number = issue_number
        self.title = title
        self.owner = owner
        self.repo = repo


class _FakeQueue:
    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self._logs: list[str] = []

    def assign(
        self, *, issue_number: int, title: str = "", owner: str = "", repo: str = ""
    ) -> _FakeIssue:
        self.issues.append({"number": issue_number, "status": "queued"})
        return _FakeIssue(issue_number, title, owner, repo)

    def list_all(self) -> list[dict[str, Any]]:
        return self.issues

    def status(self) -> dict[str, Any]:
        return {
            "running": len([i for i in self.issues if i["status"] == "running"]),
            "queued": len(self.issues),
        }

    def start(self, issue_number: int) -> None:
        for i in self.issues:
            if i["number"] == issue_number:
                i["status"] = "running"

    def complete(self, issue_number: int) -> None:
        for i in self.issues:
            if i["number"] == issue_number:
                i["status"] = "completed"

    def fail(self, issue_number: int, error: str = "") -> None:
        for i in self.issues:
            if i["number"] == issue_number:
                i["status"] = "failed"

    def add_log(self, issue_number: int, msg: str) -> None:
        self._logs.append(f"#{issue_number}: {msg}")


# ---------------------------------------------------------------------------
# Fake reactor
# ---------------------------------------------------------------------------


class _FakeReactor:
    def __init__(self) -> None:
        self.emitted: list[Any] = []

    def emit(self, event: Any) -> None:
        self.emitted.append(event)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Clear the _fetch_github_items cache between tests."""
    _issues_cache.clear()
    _issues_cache.update({"data": None, "fetched_at": 0.0})


@pytest.fixture
def fakes() -> tuple[_FakeQueue, _FakeReactor]:
    return _FakeQueue(), _FakeReactor()


@pytest.fixture
def app(fakes: tuple[_FakeQueue, _FakeReactor]) -> FastAPI:
    q, r = fakes
    application = FastAPI()
    application.include_router(router)
    container = SimpleNamespace(
        route_request=AsyncMock(),
        auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
    )
    application.state.container = container
    configure_mason_router(queue=q, reactor=r, container=container)
    return application


@pytest.fixture
def client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# POST /assign
# ---------------------------------------------------------------------------


class TestAssignIssue:
    @pytest.mark.asyncio
    async def test_assign_returns_queued_status(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/v1/stronghold/mason/assign",
            json={"issue_number": 42, "title": "Fix bug", "owner": "org", "repo": "repo"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"
        assert data["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_assign_missing_issue_number_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/v1/stronghold/mason/assign",
            json={"title": "no number"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "issue_number" in resp.json()["error"]


# ---------------------------------------------------------------------------
# POST /review-pr
# ---------------------------------------------------------------------------


class TestReviewPr:
    @pytest.mark.asyncio
    async def test_review_emits_event_and_returns_queued(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await client.post(
            "/v1/stronghold/mason/review-pr",
            json={"pr_number": 101, "owner": "org", "repo": "repo"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["pr_number"] == 101
        assert len(reactor.emitted) == 1
        assert reactor.emitted[0].name == "mason.pr_review_requested"

    @pytest.mark.asyncio
    async def test_review_missing_pr_number_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/v1/stronghold/mason/review-pr",
            json={"owner": "org"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "pr_number" in resp.json()["error"]


# ---------------------------------------------------------------------------
# GET /queue + GET /status
# ---------------------------------------------------------------------------


class TestQueueAndStatus:
    @pytest.mark.asyncio
    async def test_get_queue_returns_issues(self, client: httpx.AsyncClient) -> None:
        # Seed by assigning
        await client.post(
            "/v1/stronghold/mason/assign",
            json={"issue_number": 1, "owner": "o", "repo": "r"},
            headers=_AUTH_HEADERS,
        )
        resp = await client.get("/v1/stronghold/mason/queue", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["issues"]) == 1

    @pytest.mark.asyncio
    async def test_get_status_returns_running_count(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/stronghold/mason/status", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "queued" in data


# ---------------------------------------------------------------------------
# GET /issues (proxied GitHub fetch)
# ---------------------------------------------------------------------------


class TestListGithubIssues:
    @pytest.mark.asyncio
    async def test_missing_params_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/stronghold/mason/issues", headers=_AUTH_HEADERS)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_successful_fetch(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_result = SimpleNamespace(
            success=True,
            content=json.dumps(
                [
                    {"number": 1, "title": "Bug", "labels": ["bug"]},
                    {"number": 2, "title": "Feature", "labels": ["enhancement"]},
                ]
            ),
        )
        mock_exec = AsyncMock(return_value=fake_result)
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=mock_exec),
        )
        resp = await client.get(
            "/v1/stronghold/mason/issues?owner=org&repo=repo",
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert "bug" in data["labels"]

    @pytest.mark.asyncio
    async def test_cache_hit_skips_github_call(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time

        _issues_cache.update(
            {
                "data": {"items": [], "total": 5, "labels": []},
                "key": "org/repo",
                "fetched_at": time.monotonic(),
            }
        )
        mock_exec = AsyncMock()
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=mock_exec),
        )
        resp = await client.get(
            "/v1/stronghold/mason/issues?owner=org&repo=repo",
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 5
        mock_exec.assert_not_awaited()  # cached — no API call

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_502(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_result = SimpleNamespace(success=False, error="rate limited")
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=AsyncMock(return_value=fake_result)),
        )
        resp = await client.get(
            "/v1/stronghold/mason/issues?owner=org&repo=repo",
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_stale_cache(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If GitHub fails but stale cache exists, return stale data."""
        _issues_cache.update(
            {
                "data": {"items": [], "total": 3, "labels": []},
                "key": "org/repo",
                "fetched_at": 0.0,  # stale
            }
        )
        fake_result = SimpleNamespace(success=False, error="timeout")
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=AsyncMock(return_value=fake_result)),
        )
        resp = await client.get(
            "/v1/stronghold/mason/issues?owner=org&repo=repo",
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 3


# ---------------------------------------------------------------------------
# GET /scan
# ---------------------------------------------------------------------------


class TestScanCodebase:
    @pytest.mark.asyncio
    async def test_returns_suggestions(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stronghold.tools.scanner import IssueSuggestion

        fake_suggestion = IssueSuggestion(
            title="test: add FakeX",
            category="missing_fake",
            files=("src/protocols/x.py",),
            description="desc",
            what_youll_learn="learn",
            acceptance_criteria=("done",),
        )
        monkeypatch.setattr(
            "stronghold.tools.scanner.scan_for_good_first_issues",
            lambda root: [fake_suggestion],
        )
        resp = await client.get("/v1/stronghold/mason/scan", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["suggestions"][0]["title"] == "test: add FakeX"
        assert "github_payload" in data["suggestions"][0]


# ---------------------------------------------------------------------------
# POST /scan/create
# ---------------------------------------------------------------------------


class TestCreateScannedIssues:
    @pytest.mark.asyncio
    async def test_missing_owner_repo_returns_400(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/v1/stronghold/mason/scan/create",
            json={"all": True},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_creates_issue_from_scan(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stronghold.tools.scanner import IssueSuggestion

        suggestion = IssueSuggestion(
            title="test: add FakeY",
            category="missing_fake",
            files=("src/protocols/y.py",),
            description="desc",
            what_youll_learn="learn",
            acceptance_criteria=("crit",),
        )
        monkeypatch.setattr(
            "stronghold.tools.scanner.scan_for_good_first_issues",
            lambda root: [suggestion],
        )
        create_result = SimpleNamespace(success=True, content='{"number":999}')
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=AsyncMock(return_value=create_result)),
        )
        resp = await client.post(
            "/v1/stronghold/mason/scan/create",
            json={"all": True, "owner": "org", "repo": "repo"},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_create_with_specific_indices(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stronghold.tools.scanner import IssueSuggestion

        suggestions = [
            IssueSuggestion(
                title=f"test: item{i}",
                category="c",
                files=("f",),
                description="d",
                what_youll_learn="l",
                acceptance_criteria=("a",),
            )
            for i in range(5)
        ]
        monkeypatch.setattr(
            "stronghold.tools.scanner.scan_for_good_first_issues",
            lambda root: suggestions,
        )
        create_result = SimpleNamespace(success=True, content='{"number":1}')
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=AsyncMock(return_value=create_result)),
        )
        resp = await client.post(
            "/v1/stronghold/mason/scan/create",
            json={"indices": [0, 2, 99], "owner": "org", "repo": "repo"},
            headers=_AUTH_HEADERS,
        )
        data = resp.json()
        assert data["created"] == 2  # 0, 2 valid; 99 out of range
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_create_with_github_error(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stronghold.tools.scanner import IssueSuggestion

        suggestion = IssueSuggestion(
            title="test: err",
            category="c",
            files=("f",),
            description="d",
            what_youll_learn="l",
            acceptance_criteria=("a",),
        )
        monkeypatch.setattr(
            "stronghold.tools.scanner.scan_for_good_first_issues",
            lambda root: [suggestion],
        )
        fail_result = SimpleNamespace(success=False, error="forbidden")
        monkeypatch.setattr(
            "stronghold.tools.github.GitHubToolExecutor",
            lambda: SimpleNamespace(execute=AsyncMock(return_value=fail_result)),
        )
        resp = await client.post(
            "/v1/stronghold/mason/scan/create",
            json={"indices": [0], "owner": "org", "repo": "repo"},
            headers=_AUTH_HEADERS,
        )
        data = resp.json()
        assert data["created"] == 0
        assert len(data["errors"]) == 1
        assert "forbidden" in data["errors"][0]


# ---------------------------------------------------------------------------
# POST /webhooks/github
# ---------------------------------------------------------------------------


class TestGithubWebhook:
    """Webhook tests now require GITHUB_WEBHOOK_SECRET and signed payloads."""

    _SECRET = "test-webhook-secret"

    @pytest.fixture(autouse=True)
    def _set_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", self._SECRET)

    def _signed_post(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        event: str,
    ) -> Any:
        """Build a signed webhook request."""
        body = json.dumps(payload).encode()
        sig = hmac.new(self._SECRET.encode(), body, hashlib.sha256).hexdigest()
        return client.post(
            "/v1/stronghold/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": event,
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )

    @pytest.mark.asyncio
    async def test_issue_assigned_with_builders_label_logs_only(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        """Issues with builders label are logged, not dispatched directly."""
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "labeled",
                "issue": {
                    "number": 7,
                    "title": "Bug fix",
                    "labels": [{"name": "builders"}],
                },
                "repository": {"owner": {"login": "org"}, "name": "repo"},
            },
            "issues",
        )
        assert resp.status_code == 200
        assert len(reactor.emitted) == 0

    @pytest.mark.asyncio
    async def test_issue_without_builders_label_ignored(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        """Issues without builders label are ignored."""
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "assigned",
                "issue": {
                    "number": 8,
                    "title": "Random issue",
                    "labels": [{"name": "bug"}],
                },
                "repository": {"owner": {"login": "org"}, "name": "repo"},
            },
            "issues",
        )
        assert resp.status_code == 200
        assert len(reactor.emitted) == 0

    @pytest.mark.asyncio
    async def test_pr_opened_event_emits(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "opened",
                "pull_request": {"number": 100, "title": "feat: add X", "user": {"login": "mason"}},
            },
            "pull_request",
        )
        assert resp.status_code == 200
        assert reactor.emitted[0].name == "pr.opened"

    @pytest.mark.asyncio
    async def test_pr_review_submitted_emits(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "submitted",
                "pull_request": {"number": 50},
                "review": {"state": "approved", "user": {"login": "alice"}, "body": "lgtm"},
            },
            "pull_request_review",
        )
        assert resp.status_code == 200
        assert reactor.emitted[0].name == "pr.reviewed"
        assert reactor.emitted[0].data["review_state"] == "approved"

    @pytest.mark.asyncio
    async def test_issue_comment_on_pr_emits(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "created",
                "issue": {"number": 88, "pull_request": {"url": "..."}},
                "comment": {"user": {"login": "bob"}, "body": "fix this"},
            },
            "issue_comment",
        )
        assert resp.status_code == 200
        assert reactor.emitted[0].name == "pr.commented"

    @pytest.mark.asyncio
    async def test_issue_comment_on_non_pr_ignored(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await self._signed_post(
            client,
            {
                "action": "created",
                "issue": {"number": 77},
                "comment": {"user": {"login": "bob"}, "body": "ok"},
            },
            "issue_comment",
        )
        assert resp.status_code == 200
        assert len(reactor.emitted) == 0

    @pytest.mark.asyncio
    async def test_unrecognized_event_returns_ok(
        self, client: httpx.AsyncClient, fakes: tuple[_FakeQueue, _FakeReactor]
    ) -> None:
        _, reactor = fakes
        resp = await self._signed_post(client, {"action": "created"}, "star")
        assert resp.status_code == 200
        assert len(reactor.emitted) == 0


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature_passes(self) -> None:
        body = b'{"test": true}'
        secret = "my-secret"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        sig = f"sha256={expected}"
        assert _verify_signature(body, secret, sig) is True

    def test_invalid_signature_fails(self) -> None:
        assert _verify_signature(b"body", "secret", "sha256=wrong") is False

    def test_missing_sha256_prefix_fails(self) -> None:
        assert _verify_signature(b"body", "secret", "md5=abc") is False

    @pytest.mark.asyncio
    async def test_webhook_with_secret_validates_signature(
        self, app: FastAPI, fakes: tuple[_FakeQueue, _FakeReactor], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
        body = json.dumps({"action": "ping"}).encode()
        expected = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/v1/stronghold/webhooks/github",
                content=body,
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Hub-Signature-256": f"sha256={expected}",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_webhook_with_bad_signature_returns_401(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/v1/stronghold/webhooks/github",
                content=b'{"action":"ping"}',
                headers={
                    "X-GitHub-Event": "ping",
                    "X-Hub-Signature-256": "sha256=invalid",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# _dispatch_mason (background task) — just the logic, not the asyncio.create_task
# ---------------------------------------------------------------------------


class TestDispatchMason:
    @pytest.mark.asyncio
    async def test_dispatch_no_container_fails_issue(self) -> None:
        from stronghold.api.routes.mason import _dispatch_mason, _state

        queue = _FakeQueue()
        _state["queue"] = queue
        _state["container"] = None

        issue = _FakeIssue(42, "Fix bug", "org", "repo")
        queue.assign(issue_number=42)
        await _dispatch_mason(issue)
        assert any(i["status"] == "failed" for i in queue.issues)

    @pytest.mark.asyncio
    async def test_dispatch_workspace_failure_fails_issue(self) -> None:
        from stronghold.api.routes.mason import _dispatch_mason, _state

        queue = _FakeQueue()
        _state["queue"] = queue
        _state["container"] = SimpleNamespace(route_request=AsyncMock())

        ws_fail = SimpleNamespace(success=False, error="disk full")
        with patch(
            "stronghold.tools.workspace.WorkspaceManager",
            return_value=SimpleNamespace(execute=AsyncMock(return_value=ws_fail)),
        ):
            issue = _FakeIssue(42, "Fix bug", "org", "repo")
            queue.assign(issue_number=42)
            await _dispatch_mason(issue)
        assert any(i["status"] == "failed" for i in queue.issues)

    @pytest.mark.asyncio
    async def test_dispatch_success_completes_issue(self) -> None:
        from stronghold.api.routes.mason import _dispatch_mason, _state

        queue = _FakeQueue()
        container = SimpleNamespace(route_request=AsyncMock())
        _state["queue"] = queue
        _state["container"] = container

        ws_ok = SimpleNamespace(
            success=True,
            content=json.dumps({"path": "/tmp/ws", "branch": "mason/42"}),
        )
        with patch(
            "stronghold.tools.workspace.WorkspaceManager",
            return_value=SimpleNamespace(execute=AsyncMock(return_value=ws_ok)),
        ):
            issue = _FakeIssue(42, "Fix bug", "org", "repo")
            queue.assign(issue_number=42)
            await _dispatch_mason(issue)
        assert any(i["status"] == "completed" for i in queue.issues)
        container.route_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_route_request_failure_fails_issue(self) -> None:
        from stronghold.api.routes.mason import _dispatch_mason, _state

        queue = _FakeQueue()
        container = SimpleNamespace(route_request=AsyncMock(side_effect=RuntimeError("llm broke")))
        _state["queue"] = queue
        _state["container"] = container

        ws_ok = SimpleNamespace(
            success=True,
            content=json.dumps({"path": "/tmp/ws", "branch": "mason/42"}),
        )
        with patch(
            "stronghold.tools.workspace.WorkspaceManager",
            return_value=SimpleNamespace(execute=AsyncMock(return_value=ws_ok)),
        ):
            issue = _FakeIssue(42, "Fix bug", "org", "repo")
            queue.assign(issue_number=42)
            await _dispatch_mason(issue)
        assert any(i["status"] == "failed" for i in queue.issues)
        assert any("llm broke" in log for log in queue._logs)
