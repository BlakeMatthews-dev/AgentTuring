"""Integration tests for api/routes/dashboard.py — HTML page serving, auth, static assets.

Covers:
- _serve_page: found vs 404, CSP headers, no-cache headers
- _serve_static: found vs 404, content-type + no-cache headers
- _check_auth: no container, auth header, session cookie, invalid creds
- Every Turing surface route (hub, chat, notebook, blog, profile, memory, canvas)
- Login/logout/callback routes (public, no auth)
- Static asset routes (styles/*, components/*, assets/*, auth.js)
"""

from __future__ import annotations

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
    _serve_page,
    _serve_static,
)
from stronghold.api.routes.dashboard import (
    router as dashboard_router,
)
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
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
from tests.fakes import FakeLLMClient, FakePromptManager

AUTH_HEADER = {"Authorization": "Bearer sk-test"}

# The Turing field console's five surfaces + hub + canvas.
_SURFACE_PATHS = [
    "/dashboard",
    "/dashboard/chat",
    "/dashboard/notebook",
    "/dashboard/blog",
    "/dashboard/profile",
    "/dashboard/memory",
    "/dashboard/canvas",
]


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
        # default-src must stay tight; unsafe-* relaxations are only allowed on
        # script-src (Babel standalone needs unsafe-eval for in-browser JSX).
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


# ── _serve_static ──────────────────────────────────────────────────


class TestServeStatic:
    def test_existing_asset_returns_content(self) -> None:
        """_serve_static returns the real file, not a stub."""
        resp = _serve_static("auth.js", "application/javascript")
        assert resp.media_type == "application/javascript"
        body = resp.body.decode("utf-8")
        assert "not found" not in body.lower()
        assert len(body) > 50, "auth.js body looks like a stub"

    def test_nonexistent_asset_returns_404(self) -> None:
        resp = _serve_static("nonexistent_xyz.js", "application/javascript")
        assert resp.status_code == 404

    def test_no_cache_headers_on_asset(self) -> None:
        resp = _serve_static("auth.js", "application/javascript")
        assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
        assert resp.headers.get("pragma") == "no-cache"


# ── _check_auth ────────────────────────────────────────────────────


class TestCheckAuth:
    def test_no_container_returns_false(self) -> None:
        """When request.app.state has no container, auth check returns False."""
        app = FastAPI()
        app.include_router(dashboard_router)

        with TestClient(app) as client:
            resp = client.get("/dashboard/chat", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_valid_auth_header_grants_access(self) -> None:
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get("/dashboard/chat", headers=AUTH_HEADER)
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
                "/dashboard/chat",
                headers={"Authorization": "Bearer bad-token"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_valid_session_cookie_grants_access(self) -> None:
        """A valid session cookie is accepted for auth — no login redirect."""
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/notebook",
                cookies={"stronghold_session": "sk-test"},
                follow_redirects=False,
            )
            assert resp.status_code != 302, (
                f"Valid cookie was rejected: {resp.status_code} loc={resp.headers.get('location')}"
            )
            assert resp.headers.get("location") != "/login"
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
                "/dashboard/chat",
                cookies={"stronghold_session": "bad-cookie"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_no_auth_no_cookie_redirects(self) -> None:
        """No auth header and no cookie redirects to login."""
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get("/dashboard/chat", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"] == "/login"

    def test_empty_cookie_redirects(self) -> None:
        """Empty cookie value redirects to login."""
        app = _build_authenticated_app()
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/chat",
                cookies={"stronghold_session": ""},
                follow_redirects=False,
            )
            assert resp.status_code == 302


# ── Dashboard page routes (authenticated) ──────────────────────────


class TestDashboardPageRoutes:
    """Every Turing surface must serve real HTML under valid auth."""

    @pytest.fixture
    def authed_app(self) -> FastAPI:
        return _build_authenticated_app()

    @pytest.mark.parametrize("path", _SURFACE_PATHS)
    def test_authenticated_page_returns_html(self, authed_app: FastAPI, path: str) -> None:
        with TestClient(authed_app) as client:
            resp = client.get(path, headers=AUTH_HEADER)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"
            assert "text/html" in resp.headers["content-type"]
            body = resp.text
            assert "<" in body and "</" in body
            assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"

    @pytest.mark.parametrize("path", _SURFACE_PATHS)
    def test_unauthenticated_page_redirects_to_login(self, authed_app: FastAPI, path: str) -> None:
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
        with TestClient(app) as client:
            resp = client.get("/login")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            body = resp.text.lower()
            assert "<html" in body or "<!doctype" in body

    def test_login_callback_returns_html(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/login/callback")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_logout_clears_storage_and_returns_html(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/logout")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            body = resp.text
            # The Phosphor-Noir logout page uses "WIRE · SEVERED" as the
            # handler-facing string; the client-side script still clears
            # localStorage + sessionStorage + cookies.
            assert "localStorage.clear" in body
            assert "sessionStorage.clear" in body

    def test_logout_sets_delete_cookie_headers(self, app: FastAPI) -> None:
        """/logout must emit Set-Cookie headers with Max-Age=0 for each
        session cookie — not just render logout JS."""
        with TestClient(app) as client:
            resp = client.get("/logout")
            assert resp.status_code == 200

            set_cookie_headers = resp.headers.get_list("set-cookie")
            assert set_cookie_headers, "/logout must emit Set-Cookie headers"
            for raw in set_cookie_headers:
                lower = raw.lower()
                assert "max-age=0" in lower or "expires=thu, 01 jan 1970" in lower, (
                    f"Set-Cookie header is not a deletion: {raw!r}"
                )


# ── Static asset routes ────────────────────────────────────────────


class TestStaticAssetRoutes:
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

    def test_styles_css_returns_css(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/styles/colors_and_type.css")
            assert resp.status_code == 200
            assert "text/css" in resp.headers["content-type"]

    def test_component_jsx_returned_as_text_babel(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/components/ui.jsx")
            assert resp.status_code == 200
            assert "text/babel" in resp.headers["content-type"]

    def test_asset_svg_returns_image(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/assets/logo-seal.svg")
            assert resp.status_code == 200
            assert "image/svg+xml" in resp.headers["content-type"]

    def test_js_has_no_cache_headers(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/auth.js")
            assert resp.headers.get("cache-control") == "no-cache, no-store, must-revalidate"
            assert resp.headers.get("pragma") == "no-cache"
            assert resp.headers.get("expires") == "0"

    def test_non_css_in_styles_rejected(self, app: FastAPI) -> None:
        """The styles endpoint must only serve .css files — anything else 404."""
        with TestClient(app) as client:
            resp = client.get("/dashboard/styles/evil.js")
            assert resp.status_code == 404

    def test_non_jsx_in_components_rejected(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/components/evil.js")
            assert resp.status_code == 404

    def test_unknown_image_ext_rejected(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/assets/evil.exe")
            assert resp.status_code == 404


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

    def test_csp_allows_unpkg_for_react_babel(self) -> None:
        """The Phosphor-Noir bundle loads React + Babel from unpkg.com
        with integrity hashes. The CSP must explicitly whitelist unpkg
        as a full origin token — parsed via urlsplit and matched by
        exact host equality, not substring containment (which would
        also pass for attacker-controlled hosts like
        ``https://unpkg.com.evil.com``)."""
        from urllib.parse import urlsplit

        resp = _serve_page("login.html")
        csp = resp.headers.get("content-security-policy", "")
        # Split on ';' (directive boundary) and whitespace (source boundary),
        # parse each http(s) source as a URL, and assert exact host equality.
        whitelisted_hosts: set[str] = set()
        for directive in csp.split(";"):
            for token in directive.strip().split():
                if token.startswith(("http://", "https://")):
                    parts = urlsplit(token)
                    if parts.scheme == "https" and parts.path in ("", "/"):
                        whitelisted_hosts.add(parts.netloc)
        assert any(host == "unpkg.com" for host in whitelisted_hosts), (
            f"CSP does not whitelist the exact host unpkg.com; got {whitelisted_hosts!r}"
        )

    def test_csp_allows_unsafe_eval_for_babel_jsx(self) -> None:
        """Babel standalone transforms JSX at runtime, which requires
        'unsafe-eval' in script-src."""
        resp = _serve_page("login.html")
        csp = resp.headers.get("content-security-policy", "")
        script_src_segment = next(
            (seg for seg in csp.split(";") if "script-src" in seg),
            "",
        )
        assert "'unsafe-eval'" in script_src_segment
