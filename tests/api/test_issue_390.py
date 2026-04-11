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
            assert "version" in data
            assert "python_version" in data
            assert "service" in data
            assert data["service"] == "stronghold"

    def test_version_field_is_populated(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "version" in data
            assert data["version"] != ""

    def test_python_version_format(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            python_version = data["python_version"]
            assert isinstance(python_version, str)
            assert python_version.startswith("3.")
            assert "." in python_version
            assert len(python_version.split(".")) >= 2


class TestInvalidEndpoint:
    def test_invalid_endpoint_returns_404(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/invalid")
            assert resp.status_code == 404

    def test_invalid_endpoint_response_has_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/invalid").json()
            # FastAPI's default 404 shape is {"detail": "Not Found"}
            assert "detail" in data


class TestServiceName:
    def test_service_field_is_stronghold(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert data["service"] == "stronghold"


class TestResponseValidity:
    def test_response_is_valid_json(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)


class TestVersionFormat:
    def test_version_matches_semver_pattern(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            version = data["version"]
            assert isinstance(version, str)
            assert version != ""
            import re

            assert re.match(r"^\d+\.\d+\.\d+$", version)


class TestPythonVersionField:
    def test_python_version_field_is_not_empty(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "python_version" in data
            assert data["python_version"] != ""


class TestVersionEndpointSuccess:
    def test_get_version_success_status_code(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200

    def test_get_version_success_valid_json(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)

    def test_get_version_success_has_version_field(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "version" in data

    def test_get_version_success_has_python_version_field(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "python_version" in data

    def test_get_version_success_has_service_field(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "service" in data
            assert data["service"] == "stronghold"


class TestVersionSource:
    def test_version_matches_package_version(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            version = data["version"]
            from stronghold import __version__

            assert version == __version__


class TestPythonVersionAccuracy:
    def test_python_version_matches_sys_version(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            python_version = data["python_version"]
            import sys

            assert python_version == sys.version
