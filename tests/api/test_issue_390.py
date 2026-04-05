"""Tests for version endpoint."""

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
    app.include_router(status_router)
    container = make_test_container()
    app.state.container = container
    return app

class TestVersionEndpoint:
    def test_get_version_success(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "version" in data
            assert "python_version" in data
            assert "service" in data
            assert data["service"] == "stronghold"

    def test_version_field_is_non_empty_string(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert isinstance(data["version"], str)
            assert data["version"].strip() != ""

    def test_python_version_field_is_populated(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert isinstance(data["python_version"], str)
            assert data["python_version"].strip() != ""