"""Tests for scheduling API routes.

Covers:
- POST /v1/stronghold/schedules — create with auth + cron validation + max tasks
- GET /v1/stronghold/schedules — list user's schedules
- GET /v1/stronghold/schedules/{id} — get one
- PUT /v1/stronghold/schedules/{id} — update
- DELETE /v1/stronghold/schedules/{id} — delete
- POST /v1/stronghold/schedules/{id}/run — trigger immediately
- GET /v1/stronghold/schedules/{id}/history — past executions
- All routes require auth
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from stronghold.api.routes.schedules import router
from stronghold.scheduling.store import InMemoryScheduleStore, ScheduledTask, TaskExecution
from stronghold.types.auth import AuthContext


AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@dataclass
class _FakeAuth:
    """Minimal fake auth provider for route tests."""

    auth_context: AuthContext

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        if not authorization:
            msg = "Missing Authorization header"
            raise ValueError(msg)
        return self.auth_context


@dataclass
class _FakeContainer:
    """Minimal fake container with schedule_store and auth_provider."""

    schedule_store: InMemoryScheduleStore
    auth_provider: _FakeAuth


def _build_app(
    *,
    user_id: str = "user-1",
    org_id: str = "org-1",
) -> tuple[FastAPI, InMemoryScheduleStore]:
    """Build a test FastAPI app with the schedules router wired."""
    store = InMemoryScheduleStore()
    auth_ctx = AuthContext(
        user_id=user_id,
        username="tester",
        org_id=org_id,
        roles=frozenset({"admin", "user"}),
        auth_method="api_key",
    )
    container = _FakeContainer(
        schedule_store=store,
        auth_provider=_FakeAuth(auth_context=auth_ctx),
    )
    app = FastAPI()
    app.state.container = container
    app.include_router(router)
    return app, store


# ── Auth required ────────────────────────────────────────────────────


class TestAuthRequired:
    def test_create_requires_auth(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post("/v1/stronghold/schedules", json={"name": "x", "schedule": "0 8 * * *"})
        assert resp.status_code == 401

    def test_list_requires_auth(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.get("/v1/stronghold/schedules")
        assert resp.status_code == 401


# ── Create ───────────────────────────────────────────────────────────


class TestCreateRoute:
    def test_create_success(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={
                "name": "Morning summary",
                "schedule": "0 8 * * *",
                "prompt": "Summarize emails",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] != ""
        assert data["name"] == "Morning summary"

    def test_create_invalid_cron(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "Bad", "schedule": "not valid", "prompt": "x"},
        )
        assert resp.status_code == 400
        assert "cron" in resp.json()["detail"].lower()

    def test_create_missing_name(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"schedule": "0 8 * * *", "prompt": "x"},
        )
        assert resp.status_code == 400


# ── List ─────────────────────────────────────────────────────────────


class TestListRoute:
    def test_list_returns_user_tasks(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        # Create two tasks
        for name in ("Task A", "Task B"):
            client.post(
                "/v1/stronghold/schedules",
                headers=AUTH_HEADER,
                json={"name": name, "schedule": "0 8 * * *", "prompt": "x"},
            )
        resp = client.get("/v1/stronghold/schedules", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert len(resp.json()["schedules"]) == 2


# ── Get ──────────────────────────────────────────────────────────────


class TestGetRoute:
    def test_get_existing(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        create_resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "My task", "schedule": "0 8 * * *", "prompt": "x"},
        )
        task_id = create_resp.json()["id"]
        resp = client.get(f"/v1/stronghold/schedules/{task_id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["name"] == "My task"

    def test_get_nonexistent(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.get("/v1/stronghold/schedules/nope", headers=AUTH_HEADER)
        assert resp.status_code == 404


# ── Update ───────────────────────────────────────────────────────────


class TestUpdateRoute:
    def test_update_success(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        create_resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "Original", "schedule": "0 8 * * *", "prompt": "x"},
        )
        task_id = create_resp.json()["id"]
        resp = client.put(
            f"/v1/stronghold/schedules/{task_id}",
            headers=AUTH_HEADER,
            json={"name": "Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"


# ── Delete ───────────────────────────────────────────────────────────


class TestDeleteRoute:
    def test_delete_success(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        create_resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "To delete", "schedule": "0 8 * * *", "prompt": "x"},
        )
        task_id = create_resp.json()["id"]
        resp = client.delete(f"/v1/stronghold/schedules/{task_id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        # Confirm deleted
        get_resp = client.get(f"/v1/stronghold/schedules/{task_id}", headers=AUTH_HEADER)
        assert get_resp.status_code == 404


# ── Run now ──────────────────────────────────────────────────────────


class TestRunNow:
    def test_run_now_returns_accepted(self) -> None:
        app, _ = _build_app()
        client = TestClient(app)
        create_resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "Run me", "schedule": "0 8 * * *", "prompt": "Do it"},
        )
        task_id = create_resp.json()["id"]
        resp = client.post(f"/v1/stronghold/schedules/{task_id}/run", headers=AUTH_HEADER)
        assert resp.status_code == 202
        assert resp.json()["status"] == "triggered"


# ── History ──────────────────────────────────────────────────────────


class TestHistory:
    def test_get_history(self) -> None:
        app, store = _build_app()
        client = TestClient(app)
        create_resp = client.post(
            "/v1/stronghold/schedules",
            headers=AUTH_HEADER,
            json={"name": "With history", "schedule": "0 8 * * *", "prompt": "x"},
        )
        task_id = create_resp.json()["id"]

        # Record executions directly in the store (simulating Reactor runs)
        import asyncio
        import time as _time

        asyncio.run(
            store.record_execution(
                task_id,
                TaskExecution(
                    id="exec-1",
                    task_id=task_id,
                    started_at=_time.time(),
                    completed_at=_time.time() + 2,
                    status="success",
                    result_preview="Done",
                ),
            )
        )

        resp = client.get(f"/v1/stronghold/schedules/{task_id}/history", headers=AUTH_HEADER)
        assert resp.status_code == 200
        history = resp.json()["history"]
        assert len(history) == 1
        assert history[0]["status"] == "success"
