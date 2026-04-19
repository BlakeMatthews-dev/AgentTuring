"""Tests for orchestrator FastAPI routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.orchestrator.engine import WorkItem, WorkStatus
from stronghold.orchestrator.routes import router

# ── Helpers ──────────────────────────────────────────────────────────


class FakeEngine:
    """Minimal engine that satisfies the routes without real async workers."""

    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}

    def dispatch(self, **kwargs: Any) -> WorkItem:
        item = WorkItem(
            id=kwargs["work_id"],
            agent_name=kwargs["agent_name"],
            messages=kwargs["messages"],
            trigger=kwargs.get("trigger", "api"),
            priority_tier=kwargs.get("priority_tier", "P2"),
            intent_hint=kwargs.get("intent_hint", ""),
            metadata=kwargs.get("metadata", {}),
        )
        self._items[item.id] = item
        return item

    def get(self, work_id: str) -> WorkItem | None:
        return self._items.get(work_id)

    def list_items(self, status: Any = None) -> list[dict[str, object]]:
        items = list(self._items.values())
        if status is not None:
            items = [i for i in items if i.status == status]
        return [i.to_dict() for i in items]

    def cancel(self, work_id: str) -> bool:
        item = self._items.get(work_id)
        if item and item.status == WorkStatus.QUEUED:
            item.status = WorkStatus.CANCELLED
            return True
        return False

    def status(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for i in self._items.values():
            counts[i.status.value] = counts.get(i.status.value, 0) + 1
        return {
            "total": len(self._items),
            "running": 0,
            "max_concurrent": 3,
            **counts,
        }


class FakeContainer:
    """Container with a configurable agent registry."""

    def __init__(self, agent_names: list[str] | None = None) -> None:
        names = agent_names or ["mason", "auditor", "ranger"]
        self.agents: dict[str, object] = {n: object() for n in names}


@pytest.fixture()
def app() -> FastAPI:
    """Create a minimal FastAPI app with orchestrator routes wired up."""
    test_app = FastAPI()
    test_app.include_router(router)
    engine = FakeEngine()
    container = FakeContainer()
    test_app.state.orchestrator = engine
    test_app.state.container = container
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ── Engine not initialized ───────────────────────────────────────────


class TestEngineNotInitialized:
    def test_dispatch_503_when_no_engine(self) -> None:
        bare_app = FastAPI()
        bare_app.include_router(router)
        # No orchestrator on app.state
        c = TestClient(bare_app)
        resp = c.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={"agent_name": "mason", "messages": [{"role": "user", "content": "go"}]},
        )
        assert resp.status_code == 503

    def test_queue_503_when_no_engine(self) -> None:
        bare_app = FastAPI()
        bare_app.include_router(router)
        c = TestClient(bare_app)
        resp = c.get("/v1/stronghold/orchestrator/queue")
        assert resp.status_code == 503

    def test_status_503_when_no_engine(self) -> None:
        bare_app = FastAPI()
        bare_app.include_router(router)
        c = TestClient(bare_app)
        resp = c.get("/v1/stronghold/orchestrator/status")
        assert resp.status_code == 503


# ── POST /dispatch ───────────────────────────────────────────────────


class TestDispatchRoute:
    def test_dispatch_success(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "implement #42"}],
                "trigger": "api",
                "priority_tier": "P5",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["agent_name"] == "mason"
        assert data["status"] == "queued"
        assert data["trigger"] == "api"

    def test_dispatch_missing_agent_name(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={"messages": [{"role": "user", "content": "go"}]},
        )
        assert resp.status_code == 400

    def test_dispatch_missing_messages(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={"agent_name": "mason"},
        )
        assert resp.status_code == 400

    def test_dispatch_empty_messages(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={"agent_name": "mason", "messages": []},
        )
        assert resp.status_code == 400

    def test_dispatch_unknown_agent(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "nonexistent",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        assert resp.status_code == 404
        assert "nonexistent" in resp.json()["detail"]

    def test_dispatch_with_custom_id(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "id": "custom-id-123",
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        assert resp.status_code == 202
        assert resp.json()["id"] == "custom-id-123"

    def test_dispatch_with_metadata(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
                "metadata": {"issue_number": 42},
            },
        )
        assert resp.status_code == 202
        assert resp.json()["metadata"]["issue_number"] == 42


# ── POST /github-issue ───────────────────────────────────────────────


class TestGithubIssueRoute:
    def test_github_issue_success(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/github-issue",
            json={
                "issue_number": 42,
                "title": "Add caching layer",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["id"] == "gh-42"
        assert data["agent_name"] == "mason"
        assert data["metadata"]["issue_number"] == 42
        assert data["metadata"]["title"] == "Add caching layer"

    def test_github_issue_missing_issue_number(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/github-issue",
            json={"title": "Something"},
        )
        assert resp.status_code == 400

    def test_github_issue_custom_agent(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/github-issue",
            json={
                "issue_number": 10,
                "agent_name": "auditor",
            },
        )
        assert resp.status_code == 202
        assert resp.json()["agent_name"] == "auditor"

    def test_github_issue_default_owner_repo(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/orchestrator/github-issue",
            json={"issue_number": 5},
        )
        assert resp.status_code == 202
        meta = resp.json()["metadata"]
        assert meta["owner"] == "Agent-StrongHold"
        assert meta["repo"] == "stronghold"


# ── GET /queue ───────────────────────────────────────────────────────


class TestQueueRoute:
    def test_queue_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/orchestrator/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["count"] == 0

    def test_queue_with_items(self, client: TestClient) -> None:
        # Dispatch two items first
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "a"}],
            },
        )
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "auditor",
                "messages": [{"role": "user", "content": "b"}],
            },
        )
        resp = client.get("/v1/stronghold/orchestrator/queue")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_queue_filter_by_status(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        resp = client.get("/v1/stronghold/orchestrator/queue?status=queued")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_queue_filter_invalid_status(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/orchestrator/queue?status=bogus")
        assert resp.status_code == 400


# ── GET /status ──────────────────────────────────────────────────────


class TestStatusRoute:
    def test_status_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/orchestrator/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_status_after_dispatch(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        resp = client.get("/v1/stronghold/orchestrator/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["queued"] == 1


# ── GET /{work_id} ───────────────────────────────────────────────────


class TestGetWorkItemRoute:
    def test_get_existing_item(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "id": "item-1",
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        resp = client.get("/v1/stronghold/orchestrator/item-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "item-1"
        assert "log" in data
        assert "result" in data

    def test_get_nonexistent_item(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/orchestrator/does-not-exist")
        assert resp.status_code == 404


# ── POST /{work_id}/cancel ───────────────────────────────────────────


class TestCancelRoute:
    def test_cancel_queued_item(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "id": "cancel-me",
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        resp = client.post("/v1/stronghold/orchestrator/cancel-me/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True
        assert data["work_id"] == "cancel-me"

    def test_cancel_nonexistent_item(self, client: TestClient) -> None:
        resp = client.post("/v1/stronghold/orchestrator/ghost/cancel")
        assert resp.status_code == 400

    def test_cancel_already_cancelled(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/orchestrator/dispatch",
            json={
                "id": "double-cancel",
                "agent_name": "mason",
                "messages": [{"role": "user", "content": "go"}],
            },
        )
        client.post("/v1/stronghold/orchestrator/double-cancel/cancel")
        # Second cancel should fail (status is no longer QUEUED)
        resp = client.post("/v1/stronghold/orchestrator/double-cancel/cancel")
        assert resp.status_code == 400
