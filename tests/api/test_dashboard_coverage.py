"""Integration tests for api/routes/dashboard.py — HTML page serving, auth, JS assets.

Covers uncovered lines in dashboard.py:
- _serve_page: found vs 404, CSP headers, no-cache headers
- _check_auth: no container, auth header, session cookie, invalid creds
- All dashboard page routes: skills, security, outcomes, agents, mcp, quota, profile, team, org
- Login/logout/callback routes (public, no auth)
- JS asset routes: auth.js, scan-report.js
- _serve_js: found vs not-found
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.dashboard import (
    _check_auth,
    _serve_js,
    _serve_page,
    router as dashboard_router,
)
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.events import Reactor
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeAuthProvider, FakeLLMClient, FakePromptManager


AUTH_HEADER = {"Authorization": "Bearer sk-test"}


# ── Shared helpers ─────────────────────────────────────────────────


def _base_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test": {
                "status": "active",
                "billing_cycle": "monthly",
                "free_tokens": 1_000_000,
            },
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


def _build_authenticated_app(
    auth_provider: Any = None,
) -> FastAPI:
    """Build a FastAPI app with dashboard router and a wired container."""
    app = FastAPI()
    app.include_router(dashboard_router)

    cfg = _base_config()
    llm = FakeLLMClient()
    prompts = FakePromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()
    learning_store = InMemoryLearningStore()
    sess = InMemorySessionStore()

    # Seed prompt synchronously via FakePromptManager's dict
    prompts.seed("agent.arbiter.soul", "You are helpful.")

    default_agent = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    agents_dict: dict[str, Agent] = {"arbiter": default_agent}

    container = Container(
        config=cfg,
        auth_provider=auth_provider or StaticKeyAuthProvider(api_key="sk-test"),
        permission_table=PermissionTable.from_config({"admin": ["*"]}),
        router=RouterEngine(InMemoryQuotaTracker()),
        classifier=ClassifierEngine(),
        quota_tracker=InMemoryQuotaTracker(),
        prompt_manager=prompts,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=sess,
        audit_log=audit_log,
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=PermissionTable.from_config(cfg.permissions),
            audit_log=audit_log,
        ),
        tracer=NoopTracingBackend(),
        context_builder=context_builder,
        intent_registry=IntentRegistry({"code": "arbiter"}),
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agent_store=InMemoryAgentStore(agents_dict, prompts),
        agents=agents_dict,
    )

    app.state.container = container
    return app


# ── _serve_page ────────────────────────────────────────────────────


class TestServePage:
    def test_existing_file_returns_200_with_html(self) -> None:
        """When the HTML file exists in the dashboard dir, returns 200."""
        resp = _serve_page("login.html")
        # login.html exists in the dashboard directory
        assert resp.status_code == 200
        assert "text/html" in resp.media_type
        body = resp.body.decode("utf-8")
        assert "<html" in body.lower() or "<!doctype" in body.lower()

    def test_csp_header_present(self) -> None:
        """Real dashboard pages always ship a locked-down CSP header."""
        resp = _serve_page("login.html")
        assert resp.status_code == 200
        assert "content-security-policy" in resp.headers
        csp = resp.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        # No inline-unsafe relaxations on default-src (check for XSS mitigation).
        # default-src should not contain 'unsafe-inline' or 'unsafe-eval'.
        default_src = csp.split(";", 1)[0]
        assert "unsafe-inline" not in default_src
        assert "unsafe-eval" not in default_src

    def test_no_cache_headers_present(self) -> None:
        """Dashboard pages must be no-cache so session state doesn't leak."""
        resp = _serve_page("login.html")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
        assert resp.headers.get("pragma") == "no-cache"
        assert resp.headers.get("expires") == "0"

    def test_nonexistent_file_returns_404(self) -> None:
        resp = _serve_page("totally_nonexistent_page_xyz.html")
        assert resp.status_code == 404
        body = resp.body.decode("utf-8")
        assert "not found" in body.lower()
        assert "totally_nonexistent_page_xyz.html" in body


# ── _serve_js ──────────────────────────────────────────────────────


class TestServeJs:
    def test_existing_js_returns_content(self) -> None:
        """_serve_js returns the real file contents, not a stub comment."""
        resp = _serve_js("auth.js")
        assert resp.media_type == "application/javascript"
        body = resp.body.decode("utf-8")
        # The "not found" comment is the single-line fallback used when the
        # file is missing. A real asset is always bigger than that.
        assert "not found" not in body.lower()
        assert len(body) > 50, "auth.js body looks like a stub"

    def test_nonexistent_js_returns_comment(self) -> None:
        resp = _serve_js("nonexistent_xyz.js")
        assert resp.media_type == "application/javascript"
        body = resp.body.decode("utf-8")
        assert "not found" in body.lower()

    def test_no_cache_headers_on_js(self) -> None:
        resp = _serve_js("auth.js")
        assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
        assert resp.headers.get("pragma") == "no-cache"


# ── _check_auth ────────────────────────────────────────────────────


class TestCheckAuth:
    def test_no_container_returns_false(self) -> None:
        """When request.app.state has no container, auth check returns False."""
        app = FastAPI()
        app.include_router(dashboard_router)
        # No container set on app.state

        with TestClient(app) as client:
            # Access a protected route — should redirect to login
            resp = client.get("/dashboard/skills", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_valid_auth_header_grants_access(self) -> None:
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get("/dashboard/skills", headers=AUTH_HEADER)
            # Real HTML is shipped in src/stronghold/dashboard/ — must be 200.
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "<" in resp.text, "expected HTML body, got empty"

    def test_invalid_auth_header_redirects(self) -> None:
        """Invalid auth header causes redirect to login."""

        class FailingAuthProvider:
            async def authenticate(
                self, authorization: str | None, headers: dict[str, str] | None = None
            ) -> AuthContext:
                msg = "Invalid token"
                raise ValueError(msg)

        app = _build_authenticated_app(auth_provider=FailingAuthProvider())
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/skills",
                headers={"Authorization": "Bearer bad-token"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_valid_session_cookie_grants_access(self) -> None:
        """A valid session cookie is accepted for auth — no login redirect.

        The behavioural contract is "auth succeeded". Whether the page
        itself renders 200 or 404 (missing template file in the test
        environment) is independent of the security path. We assert the
        explicit negative: no redirect to /login.
        """
        # Use the actual API key as the cookie value so StaticKeyAuthProvider accepts it
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/agents",
                cookies={"stronghold_session": "sk-test"},
                follow_redirects=False,
            )
            assert resp.status_code != 302, (
                f"Valid cookie was rejected: {resp.status_code} loc={resp.headers.get('location')}"
            )
            assert resp.headers.get("location") != "/login"
            # Route-level outcome: either rendered the page or template missing —
            # both prove the auth gate did not trigger a redirect.
            assert resp.status_code in {200, 404}

    def test_invalid_session_cookie_redirects(self) -> None:
        """Invalid session cookie causes redirect to login."""

        class FailingAuthProvider:
            async def authenticate(
                self, authorization: str | None, headers: dict[str, str] | None = None
            ) -> AuthContext:
                msg = "Bad token"
                raise ValueError(msg)

        app = _build_authenticated_app(auth_provider=FailingAuthProvider())
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/skills",
                cookies={"stronghold_session": "bad-cookie"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_no_auth_no_cookie_redirects(self) -> None:
        """No auth header and no cookie redirects to login."""
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get("/dashboard/skills", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_empty_cookie_redirects(self) -> None:
        """Empty cookie value redirects to login."""
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/skills",
                cookies={"stronghold_session": ""},
                follow_redirects=False,
            )
            assert resp.status_code == 302


# ── Dashboard page routes (authenticated) ──────────────────────────


class TestDashboardPageRoutes:
    """Test all protected dashboard pages with valid authentication."""

    @pytest.fixture
    def authed_app(self) -> FastAPI:
        return _build_authenticated_app()

    @pytest.mark.parametrize(
        "path",
        [
            "/dashboard/skills",
            "/dashboard/security",
            "/dashboard/outcomes",
            "/dashboard/agents",
            "/dashboard/mcp",
            "/dashboard/quota",
            "/dashboard/profile",
            "/dashboard/team",
            "/dashboard/org",
        ],
    )
    def test_authenticated_page_returns_html(self, authed_app: FastAPI, path: str) -> None:
        """Each dashboard page must serve real HTML with auth — not a 404 stub.

        The old form accepted ``200 or 404``, which silently green-lit a broken
        router. All nine HTML files ship in ``src/stronghold/dashboard/`` so a
        404 is a real regression.
        """
        with TestClient(authed_app) as client:
            resp = client.get(path, headers=AUTH_HEADER)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"
            assert "text/html" in resp.headers["content-type"]
            # Body must be a real HTML doc, not an empty/error stub.
            body = resp.text
            assert "<" in body and "</" in body
            # Responses from _serve_page must be no-cache (security hardening).
            assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"

    @pytest.mark.parametrize(
        "path",
        [
            "/dashboard/skills",
            "/dashboard/security",
            "/dashboard/outcomes",
            "/dashboard/agents",
            "/dashboard/mcp",
            "/dashboard/quota",
            "/dashboard/profile",
            "/dashboard/team",
            "/dashboard/org",
        ],
    )
    def test_unauthenticated_page_redirects_to_login(
        self, authed_app: FastAPI, path: str
    ) -> None:
        with TestClient(authed_app) as client:
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"


# ── Public routes (login, logout, callback) ────────────────────────


class TestPublicRoutes:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(dashboard_router)
        return app

    def test_login_page_returns_html(self, app: FastAPI) -> None:
        """The /login page is a real HTML file shipped with the package."""
        with TestClient(app) as client:
            resp = client.get("/login")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            # Login page has a form that posts to the auth flow.
            body = resp.text.lower()
            assert "<html" in body or "<!doctype" in body

    def test_login_callback_returns_html(self, app: FastAPI) -> None:
        """The /login/callback page is served for the OIDC redirect landing."""
        with TestClient(app) as client:
            resp = client.get("/login/callback")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_logout_clears_cookies_and_returns_html(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/logout")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

            # Body should contain logout script
            body = resp.text
            assert "Logging out" in body
            assert "localStorage.clear" in body
            assert "sessionStorage.clear" in body

    def test_logout_sets_delete_cookie_headers(self, app: FastAPI) -> None:
        """/logout must emit Set-Cookie headers with Max-Age=0 for each
        session cookie — not just render logout JS. The original test
        only asserted "setTimeout" in resp.text, which ignored the
        test's own name."""
        with TestClient(app) as client:
            resp = client.get("/logout")
            assert resp.status_code == 200

            set_cookie_headers = resp.headers.get_list("set-cookie")
            # At least one Set-Cookie header must be present, and each must
            # be a deletion (Max-Age=0 or an Expires in the past).
            assert set_cookie_headers, "/logout must emit Set-Cookie headers"
            for raw in set_cookie_headers:
                lower = raw.lower()
                assert (
                    "max-age=0" in lower
                    or "expires=thu, 01 jan 1970" in lower
                ), f"Set-Cookie header is not a deletion: {raw!r}"


# ── JS asset routes ────────────────────────────────────────────────


class TestJsAssetRoutes:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(dashboard_router)
        return app

    def test_auth_js_returns_javascript(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/auth.js")
            assert resp.status_code == 200
            assert "javascript" in resp.headers["content-type"]

    def test_scan_report_js_returns_javascript(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/scan-report.js")
            assert resp.status_code == 200
            assert "javascript" in resp.headers["content-type"]

    def test_js_has_no_cache_headers(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/auth.js")
            assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
            assert resp.headers.get("pragma") == "no-cache"
            assert resp.headers.get("expires") == "0"


# ── CSP header comprehensive check ────────────────────────────────


class TestContentSecurityPolicy:
    def test_csp_includes_required_directives(self) -> None:
        """CSP header contains every directive needed to harden the dashboard."""
        resp = _serve_page("login.html")
        assert resp.status_code == 200, "login.html missing from dashboard candidates"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "style-src" in csp
        assert "font-src" in csp
        assert "connect-src 'self'" in csp
        assert "img-src 'self' data:" in csp
