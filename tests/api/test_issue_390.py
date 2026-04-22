"""Tests for /v1/stronghold/version.

The original issue #390 file exploded the version endpoint into ~14
tests, most of which re-asserted the same keys or type of the same
field. That batch was consolidated into five behavioural tests: one
parameterised field-presence test, a semver check, a correctness check
against ``stronghold.__version__`` and ``sys.version``, and a 404 case.
"""

from __future__ import annotations

import re
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold import __version__
from stronghold.api.routes.status import router as status_router
from tests.fakes import make_test_container

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app wired with the real status router + a test container."""
    app = FastAPI()
    app.include_router(status_router)
    app.state.container = make_test_container()
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestVersionEndpoint:
    def test_returns_full_documented_payload(self, client: TestClient) -> None:
        """Version endpoint returns exactly the three documented fields
        with live values (not defaults/placeholders). Consumers (health
        probes, release dashboards) pin on this exact shape.
        """
        resp = client.get("/v1/stronghold/version")
        assert resp.status_code == 200

        body = resp.json()
        # Exact key set — no extras leaking diagnostics, no missing fields.
        assert set(body.keys()) == {"version", "python_version", "service"}
        assert body["service"] == "stronghold"
        assert body["version"] == __version__
        assert body["python_version"] == sys.version

    def test_version_matches_semver_pattern(self, client: TestClient) -> None:
        """Release tooling parses this field as semver — verify the
        format, not just that the string exists."""
        body = client.get("/v1/stronghold/version").json()
        assert SEMVER_RE.match(body["version"]), (
            f"version {body['version']!r} is not semver"
        )

    def test_python_version_starts_with_major_three(
        self, client: TestClient
    ) -> None:
        """Stronghold is a Python 3 project — smoke guard against a
        misconfigured base image accidentally serving Python 2."""
        body = client.get("/v1/stronghold/version").json()
        assert body["python_version"].startswith("3.")

    def test_unknown_subroute_returns_404_with_detail(
        self, client: TestClient
    ) -> None:
        """Unknown routes under the status router surface FastAPI's
        default 404 ``{"detail": "Not Found"}`` shape — consumers rely
        on ``detail`` being present to distinguish from 5xx."""
        resp = client.get("/v1/stronghold/invalid")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}

    def test_version_endpoint_is_idempotent(self, client: TestClient) -> None:
        """The endpoint must not accumulate state — two back-to-back
        calls produce identical payloads."""
        a = client.get("/v1/stronghold/version").json()
        b = client.get("/v1/stronghold/version").json()
        assert a == b
