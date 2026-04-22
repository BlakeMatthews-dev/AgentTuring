"""Tests for dashboard routes (dashboard.py).

Dashboard pages are server-side auth-gated (see _check_auth in
stronghold.api.routes.dashboard). When the request has no valid
session cookie or Authorization header, the handler returns a 302
redirect to /login rather than the dashboard HTML.

These tests verify that the auth gate actually fires (302 -> /login)
AND that an authenticated request receives the real dashboard HTML
(so a regression that silently bypassed auth would fail here, and a
regression that broke the happy-path would fail too).

Prior versions of these tests accepted ``status in (200, 404)`` which
passed in both states: redirect-following dropped the caller at
/login (200) and any 404 would also sneak through. Both are now
asserted explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.dashboard import router as dashboard_router


# Locate the real dashboard asset directory the handler will serve from.
_DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "src" / "stronghold" / "dashboard"


class _AlwaysAllowAuthProvider:
    """Stub auth provider that accepts any non-empty Bearer token.

    Used to drive the authenticated happy-path without spinning a full
    Container. Mirrors the shape of auth_provider.authenticate as used
    by _check_auth in dashboard.py (ValueError => not authed).
    """

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> object:
        if not authorization:
            msg = "missing auth"
            raise ValueError(msg)
        return object()


class _FakeConfig:
    class _Auth:
        session_cookie_name = "stronghold_session"

    auth = _Auth()


class _FakeContainer:
    config = _FakeConfig()
    auth_provider = _AlwaysAllowAuthProvider()


@pytest.fixture
def dashboard_app() -> FastAPI:
    """App with just the dashboard router. No container attached -- the
    _check_auth helper returns False for every request, so every route
    redirects to /login. This isolates the auth-gate behavior."""
    app = FastAPI()
    app.include_router(dashboard_router)
    return app


@pytest.fixture
def authed_dashboard_app(dashboard_app: FastAPI) -> FastAPI:
    """Same router, but with a container whose auth provider always
    accepts. Lets us assert the happy-path HTML body."""
    dashboard_app.state.container = _FakeContainer()
    return dashboard_app


def _assert_redirects_to_login(resp) -> None:  # type: ignore[no-untyped-def]
    """Common assertion for every dashboard route without auth."""
    assert resp.status_code == 302, (
        f"unauthenticated dashboard should redirect, got {resp.status_code}"
    )
    assert resp.headers["location"] == "/login"


def _assert_serves_dashboard_page(resp, filename: str) -> None:  # type: ignore[no-untyped-def]
    """Assert the route served the exact file from the dashboard dir,
    not the login page and not a 404 stub."""
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    # Anti-regression: the "page not found" fallback renders a specific
    # string; the login page has a different <title>. Neither should be
    # what we see for a dashboard route with valid auth.
    assert f"Page not found: {filename}" not in body
    assert "Enter the Gates" not in body, (
        "authenticated dashboard route returned the login page -- the "
        "auth gate should have let this through"
    )
    # The real file on disk must be what we got back.
    on_disk = (_DASHBOARD_DIR / filename).read_text(encoding="utf-8")
    assert body == on_disk
    # CSP + no-cache headers are part of the dashboard contract.
    assert "default-src 'self'" in resp.headers.get("content-security-policy", "")
    assert "no-cache" in resp.headers.get("cache-control", "")


class TestDashboardRoutes:
    def test_skills_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """Unauthenticated GET /dashboard/skills redirects to /login."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/skills", follow_redirects=False)
            _assert_redirects_to_login(resp)

    def test_skills_dashboard_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI
    ) -> None:
        """Authenticated GET serves the real skills.html from disk."""
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(
                "/dashboard/skills",
                headers={"Authorization": "Bearer test-token"},
            )
            _assert_serves_dashboard_page(resp, "skills.html")

    def test_security_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """Unauthenticated GET /dashboard/security redirects to /login."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/security", follow_redirects=False)
            _assert_redirects_to_login(resp)

    def test_security_dashboard_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI
    ) -> None:
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(
                "/dashboard/security",
                headers={"Authorization": "Bearer test-token"},
            )
            _assert_serves_dashboard_page(resp, "security.html")

    def test_outcomes_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """Unauthenticated GET /dashboard/outcomes redirects to /login."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/outcomes", follow_redirects=False)
            _assert_redirects_to_login(resp)

    def test_outcomes_dashboard_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI
    ) -> None:
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(
                "/dashboard/outcomes",
                headers={"Authorization": "Bearer test-token"},
            )
            _assert_serves_dashboard_page(resp, "outcomes.html")

    def test_agents_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """Unauthenticated GET /dashboard/agents redirects to /login."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/agents", follow_redirects=False)
            _assert_redirects_to_login(resp)

    def test_agents_dashboard_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI
    ) -> None:
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(
                "/dashboard/agents",
                headers={"Authorization": "Bearer test-token"},
            )
            _assert_serves_dashboard_page(resp, "agents.html")

    def test_quota_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """Unauthenticated GET /dashboard/quota redirects to /login."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/quota", follow_redirects=False)
            _assert_redirects_to_login(resp)

    def test_quota_dashboard_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI
    ) -> None:
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(
                "/dashboard/quota",
                headers={"Authorization": "Bearer test-token"},
            )
            _assert_serves_dashboard_page(resp, "quota.html")

    def test_nonexistent_dashboard_returns_404(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/nonexistent returns 404."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/nonexistent")
            # This route does not exist on the router, so FastAPI returns 404
            assert resp.status_code == 404
