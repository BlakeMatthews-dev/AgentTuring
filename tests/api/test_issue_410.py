"""Tests for uptime endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.status import router as status_router

from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}

@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(status_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app

class TestUptimeEndpoint:
    def test_get_uptime_success(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data.get("uptime_seconds"), float)
            assert isinstance(data.get("started_at"), str)
            assert data.get("service") == "stronghold"

    def test_uptime_seconds_is_non_negative(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("uptime_seconds", -1) >= 0

    def test_uptime_seconds_is_non_negative(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert data["uptime_seconds"] >= 0

    def test_started_at_is_valid_timestamp_in_past(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            started_at = data.get("started_at")
            assert isinstance(started_at, str)

            from datetime import datetime
            try:
                parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                assert parsed < datetime.utcnow()
            except ValueError:
                pytest.fail("started_at is not a valid ISO 8601 timestamp")

    def test_started_at_is_valid_iso8601_timestamp_in_past(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            started_at = data.get("started_at")
            assert isinstance(started_at, str)

            from datetime import datetime
            try:
                parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                assert parsed < datetime.utcnow()
            except ValueError:
                pytest.fail("started_at is not a valid ISO 8601 timestamp")

    def test_response_is_valid_json_object(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)

    def test_uptime_seconds_is_non_negative_in_new_criterion(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert data["uptime_seconds"] >= 0