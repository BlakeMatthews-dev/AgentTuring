"""Route-level tests for the Builders 2.0 API endpoints.

Uses TestClient with make_test_container (no real LLM/GitHub calls).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.builders import configure_builders_router, router as builders_router
from tests.fakes import make_test_container

if TYPE_CHECKING:
    pass

AUTH = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(builders_router)
    container = make_test_container()
    app.state.container = container
    return TestClient(app)


# ── POST /runs ───────────────────────────────────────────────────────


class TestCreateRun:
    def test_creates_run_returns_state(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs",
            json={"repo_url": "https://github.com/owner/repo", "issue_number": 42},
            headers=AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert data["repo"] == "owner/repo"
        assert data["issue_number"] == 42

    def test_creates_run_with_execute_returns_202(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs",
            json={
                "repo_url": "https://github.com/owner/repo",
                "issue_number": 99,
                "execute": True,
            },
            headers=AUTH,
        )
        assert resp.status_code == 202
        assert "run_id" in resp.json()

    def test_missing_repo_url_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs",
            json={"issue_number": 42},
            headers=AUTH,
        )
        assert resp.status_code == 400

    def test_invalid_repo_url_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs",
            json={"repo_url": "not-a-url"},
            headers=AUTH,
        )
        assert resp.status_code == 400

    def test_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs",
            json={"repo_url": "https://github.com/owner/repo", "issue_number": 1},
        )
        assert resp.status_code == 401


# ── GET /runs ────────────────────────────────────────────────────────


class TestListRuns:
    def test_list_empty_returns_array(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/builders/runs", headers=AUTH)
        assert resp.status_code == 200
        assert "runs" in resp.json()

    def test_list_after_create(self, client: TestClient) -> None:
        client.post(
            "/v1/stronghold/builders/runs",
            json={"repo_url": "https://github.com/o/r", "issue_number": 1},
            headers=AUTH,
        )
        resp = client.get("/v1/stronghold/builders/runs", headers=AUTH)
        assert len(resp.json()["runs"]) >= 1


# ── GET /runs/{run_id} ──────────────────────────────────────────────


class TestGetRun:
    def test_get_existing_run(self, client: TestClient) -> None:
        create_resp = client.post(
            "/v1/stronghold/builders/runs",
            json={"repo_url": "https://github.com/o/r", "issue_number": 1},
            headers=AUTH,
        )
        run_id = create_resp.json()["run_id"]
        resp = client.get(f"/v1/stronghold/builders/runs/{run_id}", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id

    def test_get_missing_run_returns_404(self, client: TestClient) -> None:
        resp = client.get("/v1/stronghold/builders/runs/run-nonexistent", headers=AUTH)
        assert resp.status_code == 404


# ── POST /runs/{run_id}/execute ──────────────────────────────────────


class TestExecuteStage:
    def test_execute_on_missing_run_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/stronghold/builders/runs/run-missing/execute",
            headers=AUTH,
        )
        assert resp.status_code == 404
