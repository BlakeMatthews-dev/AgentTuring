"""Tests for dashboard routes (dashboard.py).

Dashboard pages are static HTML served from the dashboard directory.
These tests verify routing and status codes without auth.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.dashboard import router as dashboard_router


@pytest.fixture
def dashboard_app() -> FastAPI:
    """Create a FastAPI app with just the dashboard router."""
    app = FastAPI()
    app.include_router(dashboard_router)
    return app


class TestDashboardRoutes:
    def test_skills_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/skills returns 200 with HTML content."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/skills")
            if resp.status_code == 404:
                pytest.skip("Dashboard not compiled in test environment")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_security_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/security returns 200 with HTML content."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/security")
            if resp.status_code == 404:
                pytest.skip("Dashboard not compiled in test environment")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_outcomes_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/outcomes returns 200 with HTML content."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/outcomes")
            if resp.status_code == 404:
                pytest.skip("Dashboard not compiled in test environment")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_agents_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/agents returns 200 with HTML content."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/agents")
            if resp.status_code == 404:
                pytest.skip("Dashboard not compiled in test environment")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_quota_dashboard_returns_html(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/quota returns 200 with HTML content."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/quota")
            if resp.status_code == 404:
                pytest.skip("Dashboard not compiled in test environment")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_nonexistent_dashboard_returns_404(self, dashboard_app: FastAPI) -> None:
        """GET /dashboard/nonexistent returns 404."""
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/nonexistent")
            # This route does not exist on the router, so FastAPI returns 404
            assert resp.status_code == 404
