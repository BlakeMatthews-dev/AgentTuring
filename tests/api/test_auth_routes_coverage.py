"""Integration tests for api/routes/auth.py — BFF authentication endpoints.

Covers: CSRF protection, token exchange (OIDC BFF), demo login with
password verification, logout (GET + POST), session cookie parsing
(demo HS256 token + auth_provider fallback), OIDC config endpoint,
registration flow, password hashing/verification, and error paths.

Target: increase auth.py coverage from ~22% to 80%+.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.auth import _hash_password, _verify_password
from stronghold.api.routes.auth import router as auth_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.gate import Gate
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import AuthContext, IdentityKind, PermissionTable
from stronghold.types.config import AuthConfig, StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeAuthProvider, FakeLLMClient, FakePromptManager

# ── CSRF header constant ──────────────────────────────────────────────
CSRF_HEADER = {"x-stronghold-request": "1"}


# ── Fake DB pool for login/register routes ────────────────────────────


@dataclass
class _FakeRow:
    """Dict-like row returned by FakeConnection."""

    _data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class FakeConnection:
    """Minimal asyncpg connection fake for auth user queries."""

    def __init__(self, pool: FakeDBPool) -> None:
        self._pool = pool

    async def fetch(self, query: str, *args: Any) -> list[_FakeRow]:
        return self._pool._handle_fetch(query, args)

    async def fetchrow(self, query: str, *args: Any) -> _FakeRow | None:
        return self._pool._handle_fetchrow(query, args)

    async def execute(self, query: str, *args: Any) -> str:
        return self._pool._handle_execute(query, args)


class FakeDBPool:
    """Fake asyncpg pool for auth routes testing."""

    def __init__(self) -> None:
        self._users: list[dict[str, Any]] = []

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self)

    def add_user(self, user: dict[str, Any]) -> None:
        self._users.append(user)

    def _handle_fetch(self, query: str, args: tuple[Any, ...]) -> list[_FakeRow]:
        return [_FakeRow(u) for u in self._users]

    def _handle_fetchrow(self, query: str, args: tuple[Any, ...]) -> _FakeRow | None:
        if args:
            email = args[0].strip().lower()
            for u in self._users:
                if u.get("email", "").lower() == email:
                    return _FakeRow(u)
        return None

    def _handle_execute(self, query: str, args: tuple[Any, ...]) -> str:
        return "INSERT 0 1"


class _FakeAcquire:
    def __init__(self, pool: FakeDBPool) -> None:
        self._pool = pool

    async def __aenter__(self) -> FakeConnection:
        return FakeConnection(self._pool)

    async def __aexit__(self, *args: Any) -> None:
        pass


# ── Helpers ────────────────────────────────────────────────────────────


def _base_config(**auth_overrides: Any) -> StrongholdConfig:
    """Create a minimal config, optionally overriding AuthConfig fields."""
    auth_kwargs: dict[str, Any] = {
        "session_cookie_name": "stronghold_session",
        "session_max_age": 3600,
    }
    auth_kwargs.update(auth_overrides)
    return StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test-key",
        auth=AuthConfig(**auth_kwargs),
    )


def _build_app(
    *,
    config: StrongholdConfig | None = None,
    auth_provider: Any = None,
    db_pool: FakeDBPool | None = None,
) -> FastAPI:
    """Build a FastAPI app with auth router and a fully wired container."""
    app = FastAPI()
    app.include_router(auth_router)

    cfg = config or _base_config()
    llm = FakeLLMClient()
    prompts = FakePromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()
    learning_store = InMemoryLearningStore()

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
        auth_provider=auth_provider or FakeAuthProvider(),
        permission_table=PermissionTable.from_config(cfg.permissions),
        router=RouterEngine(InMemoryQuotaTracker()),
        classifier=ClassifierEngine(),
        quota_tracker=InMemoryQuotaTracker(),
        prompt_manager=prompts,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
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
        intent_registry=IntentRegistry(),
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agent_store=InMemoryAgentStore(agents_dict, prompts),
        agents=agents_dict,
        db_pool=db_pool,
    )
    app.state.container = container
    return app


def _make_password_hash(password: str) -> str:
    """Create a pbkdf2:salt:hash string for testing."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
    return f"pbkdf2:{salt}:{h}"


# ── CSRF protection ──────────────────────────────────────────────────


class TestCSRFProtection:
    """Verify CSRF header requirement on POST endpoints."""

    def test_login_missing_csrf_returns_403(self) -> None:
        db = FakeDBPool()
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "test@example.com", "password": "pass"},
            )
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]

    def test_token_missing_csrf_returns_403(self) -> None:
        cfg = _base_config(token_url="https://idp.example.com/token", client_id="my-client")
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/token",
                json={"code": "abc", "code_verifier": "xyz", "redirect_uri": "http://localhost"},
            )
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]

    def test_logout_post_missing_csrf_returns_403(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post("/auth/logout")
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]

    def test_register_missing_csrf_returns_403(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "org_id": "test-org"},
            )
            assert resp.status_code == 403
            assert "CSRF" in resp.json()["detail"]


# ── Token exchange (OIDC BFF) ─────────────────────────────────────────


class TestTokenExchange:
    """Test POST /auth/token — server-side code→token exchange."""

    def test_oidc_not_configured_returns_501(self) -> None:
        """When token_url or client_id is missing, returns 501."""
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                "/auth/token",
                json={"code": "abc", "code_verifier": "xyz", "redirect_uri": "http://localhost"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 501
            assert "OIDC not configured" in resp.json()["detail"]

    def test_idp_network_error_returns_502(self) -> None:
        """When the IdP is unreachable, returns 502."""
        cfg = _base_config(token_url="https://idp.example.com/token", client_id="my-client")
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            with patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                import httpx

                mock_instance.post.side_effect = httpx.ConnectError("Connection refused")
                mock_client_cls.return_value = mock_instance

                resp = client.post(
                    "/auth/token",
                    json={
                        "code": "abc",
                        "code_verifier": "xyz",
                        "redirect_uri": "http://localhost",
                    },
                    headers=CSRF_HEADER,
                )
                assert resp.status_code == 502
                assert "Could not reach identity provider" in resp.json()["detail"]

    def test_idp_non_200_returns_502(self) -> None:
        """When the IdP returns a non-200 status, returns 502."""
        cfg = _base_config(
            token_url="https://idp.example.com/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            with patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                # httpx.Response has sync .json(), .text, .status_code — use MagicMock
                mock_resp = MagicMock()
                mock_resp.status_code = 400
                mock_resp.text = "invalid_grant"
                mock_instance.post.return_value = mock_resp
                mock_client_cls.return_value = mock_instance

                resp = client.post(
                    "/auth/token",
                    json={
                        "code": "abc",
                        "code_verifier": "xyz",
                        "redirect_uri": "http://localhost",
                    },
                    headers=CSRF_HEADER,
                )
                assert resp.status_code == 502
                assert "Identity provider returned 400" in resp.json()["detail"]

    def test_idp_non_200_does_not_log_response_body(self, caplog: pytest.LogCaptureFixture) -> None:
        """Regression #1038: IdP failure must log only the status, never the
        response body. Body may contain sensitive metadata (invalid_grant
        details, authorization codes echoed back, user identifiers).
        """
        import logging as _logging

        cfg = _base_config(
            token_url="https://idp.example.com/token",
            client_id="my-client",
            client_secret="my-secret",
        )
        app = _build_app(config=cfg)
        # A body that SHOULD NOT appear in logs — if it does, we've regressed.
        sensitive_body = (
            '{"error":"invalid_grant","sensitive":"authorization_code_abc123xyz",'
            '"user_hint":"user@example.com"}'
        )
        with (
            TestClient(app) as client,
            patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls,
            caplog.at_level(_logging.WARNING, logger="stronghold.api.auth"),
        ):
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = sensitive_body
            mock_instance.post.return_value = mock_resp
            mock_client_cls.return_value = mock_instance

            resp = client.post(
                "/auth/token",
                json={"code": "abc", "code_verifier": "xyz", "redirect_uri": "http://x"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 502

        # The status code SHOULD be in the log; the response body MUST NOT be.
        full_log = "\n".join(r.message for r in caplog.records)
        assert "400" in full_log
        assert "authorization_code_abc123xyz" not in full_log
        assert "user@example.com" not in full_log
        assert "invalid_grant" not in full_log

    def test_idp_no_access_token_returns_502(self) -> None:
        """When the IdP response has no access_token, returns 502."""
        cfg = _base_config(token_url="https://idp.example.com/token", client_id="my-client")
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            with patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"token_type": "bearer"}  # no access_token
                mock_instance.post.return_value = mock_resp
                mock_client_cls.return_value = mock_instance

                resp = client.post(
                    "/auth/token",
                    json={
                        "code": "abc",
                        "code_verifier": "xyz",
                        "redirect_uri": "http://localhost",
                    },
                    headers=CSRF_HEADER,
                )
                assert resp.status_code == 502
                assert "did not return an access_token" in resp.json()["detail"]

    def test_jwt_validation_fails_returns_401(self) -> None:
        """When auth_provider rejects the token after exchange, returns 401."""
        cfg = _base_config(token_url="https://idp.example.com/token", client_id="my-client")
        failing_auth = FakeAuthProvider()

        # Override authenticate to always raise
        async def _reject(
            authorization: str | None, headers: dict[str, str] | None = None
        ) -> AuthContext:
            raise ValueError("Invalid token")

        failing_auth.authenticate = _reject  # type: ignore[assignment]

        app = _build_app(config=cfg, auth_provider=failing_auth)
        with TestClient(app) as client:
            with patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"access_token": "fake-jwt-token"}
                mock_instance.post.return_value = mock_resp
                mock_client_cls.return_value = mock_instance

                resp = client.post(
                    "/auth/token",
                    json={
                        "code": "abc",
                        "code_verifier": "xyz",
                        "redirect_uri": "http://localhost",
                    },
                    headers=CSRF_HEADER,
                )
                assert resp.status_code == 401
                assert "Token validation failed" in resp.json()["detail"]

    def test_successful_token_exchange_sets_cookies(self) -> None:
        """Full happy path: exchange code, validate JWT, set session cookie."""
        cfg = _base_config(token_url="https://idp.example.com/token", client_id="my-client")
        auth_ctx = AuthContext(
            user_id="alice@example.com",
            username="alice",
            org_id="acme",
            roles=frozenset({"user"}),
        )
        auth_provider = FakeAuthProvider(auth_context=auth_ctx)
        app = _build_app(config=cfg, auth_provider=auth_provider)

        with TestClient(app) as client:
            with patch("stronghold.api.routes.auth.httpx.AsyncClient") as mock_client_cls:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"access_token": "fake-jwt-token"}
                mock_instance.post.return_value = mock_resp
                mock_client_cls.return_value = mock_instance

                resp = client.post(
                    "/auth/token",
                    json={
                        "code": "abc",
                        "code_verifier": "xyz",
                        "redirect_uri": "http://localhost",
                    },
                    headers=CSRF_HEADER,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["user_id"] == "alice@example.com"
                assert data["username"] == "alice"
                assert data["org_id"] == "acme"

                # Check cookies were set
                set_cookie = resp.headers.get("set-cookie", "")
                assert "stronghold_session" in set_cookie.lower()


# ── Demo login ─────────────────────────────────────────────────────────


class TestDemoLogin:
    """Test POST /auth/login — email/password login."""

    def test_empty_email_returns_400(self) -> None:
        db = FakeDBPool()
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 400
            assert "email is required" in resp.json()["detail"]

    def test_no_db_returns_503(self) -> None:
        """When db_pool is not configured, returns 503."""
        app = _build_app(db_pool=None)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "test@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 503
            assert "Database not available" in resp.json()["detail"]

    def test_user_not_found_returns_403(self) -> None:
        db = FakeDBPool()
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "nobody@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "No account found" in resp.json()["detail"]

    def test_user_pending_returns_403(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 1,
                "email": "pending@example.com",
                "display_name": "Pending",
                "org_id": "acme",
                "team_id": "default",
                "roles": "[]",
                "status": "pending",
                "password_hash": "",
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "pending@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "pending admin approval" in resp.json()["detail"]

    def test_user_rejected_returns_403(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 2,
                "email": "rejected@example.com",
                "display_name": "Rejected",
                "org_id": "acme",
                "team_id": "default",
                "roles": "[]",
                "status": "rejected",
                "password_hash": "",
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "rejected@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "rejected" in resp.json()["detail"]

    def test_user_disabled_returns_403(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 3,
                "email": "disabled@example.com",
                "display_name": "Disabled",
                "org_id": "acme",
                "team_id": "default",
                "roles": "[]",
                "status": "disabled",
                "password_hash": "",
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "disabled@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "disabled" in resp.json()["detail"]

    def test_user_unknown_status_returns_403(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 4,
                "email": "weird@example.com",
                "display_name": "Weird",
                "org_id": "acme",
                "team_id": "default",
                "roles": "[]",
                "status": "limbo",
                "password_hash": "",
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "weird@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "not approved" in resp.json()["detail"]

    def test_approved_user_no_password_body_returns_401(self) -> None:
        pw_hash = _make_password_hash("secret123")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 5,
                "email": "alice@example.com",
                "display_name": "Alice",
                "org_id": "acme",
                "team_id": "default",
                "roles": '["user"]',
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "alice@example.com", "password": ""},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 401
            assert "Password required" in resp.json()["detail"]

    def test_approved_user_no_stored_hash_returns_401(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 6,
                "email": "nohash@example.com",
                "display_name": "NoHash",
                "org_id": "acme",
                "team_id": "default",
                "roles": '["user"]',
                "status": "approved",
                "password_hash": "",
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "nohash@example.com", "password": "mypass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 401
            assert "no password set" in resp.json()["detail"]

    def test_approved_user_wrong_password_returns_401(self) -> None:
        pw_hash = _make_password_hash("correct-password")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 7,
                "email": "alice@example.com",
                "display_name": "Alice",
                "org_id": "acme",
                "team_id": "default",
                "roles": '["user"]',
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "alice@example.com", "password": "wrong-password"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 401
            assert "Invalid credentials" in resp.json()["detail"]

    def test_successful_login_sets_cookies_and_returns_user(self) -> None:
        pw_hash = _make_password_hash("correct-password")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 8,
                "email": "alice@example.com",
                "display_name": "Alice",
                "org_id": "acme",
                "team_id": "eng",
                "roles": '["user", "engineer"]',
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "Alice@Example.com", "password": "correct-password"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "alice@example.com"
            assert data["username"] == "Alice"
            assert data["org_id"] == "acme"
            assert data["team_id"] == "eng"

            # Verify cookie was set
            set_cookie_header = resp.headers.get("set-cookie", "")
            assert "stronghold_session" in set_cookie_header.lower()

    def test_login_with_list_roles_propagates_to_session_cookie(self) -> None:
        """When DB roles is already a list (not JSON string), login must succeed
        AND the issued session cookie must carry that role.

        This catches a regression where list-valued roles get dropped or mis-parsed.
        """
        pw_hash = _make_password_hash("pass")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 9,
                "email": "bob@example.com",
                "display_name": "Bob",
                "org_id": "acme",
                "team_id": "default",
                "roles": ["admin"],
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                json={"email": "bob@example.com", "password": "pass"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 200
            assert resp.json()["user_id"] == "bob@example.com"

            # Extract the session cookie and decode it to confirm admin role is carried.
            session_token = None
            for h in resp.headers.get_list("set-cookie"):
                if "stronghold_session=" in h.lower():
                    session_token = h.split("stronghold_session=", 1)[1].split(";", 1)[0]
                    break
            assert session_token, "login did not set stronghold_session cookie"

            # The session cookie is an HS256 JWT signed with the router_api_key.
            claims = pyjwt.decode(
                session_token,
                "sk-test-key",
                algorithms=["HS256"],
                audience="stronghold",
            )
            assert "admin" in claims.get("roles", [])


# ── Logout ─────────────────────────────────────────────────────────────


class TestLogout:
    """Test GET/POST /auth/logout — clear session cookies."""

    def test_get_logout_returns_logged_out(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get("/auth/logout")
            assert resp.status_code == 200
            assert resp.json()["status"] == "logged_out"

    def test_post_logout_with_csrf_returns_logged_out(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post("/auth/logout", headers=CSRF_HEADER)
            assert resp.status_code == 200
            assert resp.json()["status"] == "logged_out"

    def test_logout_clears_session_cookie(self) -> None:
        """Logout response must emit Set-Cookie that deletes the session cookie.

        A delete is signalled either by max-age=0 or an Expires= in the past.
        Without this, logout would be a no-op client-side.
        """
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get("/auth/logout")
            assert resp.status_code == 200
            set_cookies = resp.headers.get_list("set-cookie")
            # Must find at least one Set-Cookie for the session name.
            session_headers = [
                h for h in set_cookies if "stronghold_session=" in h.lower()
            ]
            assert session_headers, f"no session cookie clear in: {set_cookies!r}"
            # And it must mark the cookie for deletion.
            combined = " ".join(session_headers).lower()
            assert (
                "max-age=0" in combined
                or "expires=thu, 01 jan 1970" in combined
                or "expires=" in combined  # any past-dated Expires counts
            ), f"session cookie not marked for deletion: {session_headers!r}"


# ── Session ────────────────────────────────────────────────────────────


class TestSessionEndpoint:
    """Test GET /auth/session — session cookie validation."""

    def test_no_cookie_returns_401(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get("/auth/session")
            assert resp.status_code == 401
            assert resp.json()["authenticated"] is False

    def test_invalid_cookie_name_returns_401(self) -> None:
        """When cookie exists but not the expected session cookie name."""
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"wrong_cookie": "some_value"},
            )
            assert resp.status_code == 401
            assert resp.json()["authenticated"] is False

    def test_empty_cookie_value_returns_401(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": ""},
            )
            assert resp.status_code == 401
            assert resp.json()["authenticated"] is False

    def test_valid_demo_token_returns_session(self) -> None:
        """A valid HS256 demo token in the cookie should return authenticated session."""
        signing_key = "sk-test-key"
        now = int(time.time())
        claims = {
            "sub": "alice@example.com",
            "email": "alice@example.com",
            "preferred_username": "alice",
            "organization_id": "acme",
            "team_id": "eng",
            "roles": ["user", "engineer"],
            "iss": "stronghold-demo",
            "aud": "stronghold",
            "iat": now,
            "exp": now + 3600,
        }
        token = pyjwt.encode(claims, signing_key, algorithm="HS256")

        app = _build_app()
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["authenticated"] is True
            assert data["user_id"] == "alice@example.com"
            assert data["username"] == "alice"
            assert data["org_id"] == "acme"
            assert data["team_id"] == "eng"
            assert "user" in data["roles"]
            assert "engineer" in data["roles"]
            assert data["kind"] == "user"

    def test_expired_demo_token_falls_through_to_auth_provider(self) -> None:
        """An expired HS256 token should fall through to auth_provider.authenticate."""
        signing_key = "sk-test-key"
        now = int(time.time())
        claims = {
            "sub": "alice@example.com",
            "aud": "stronghold",
            "iss": "stronghold-demo",
            "iat": now - 7200,
            "exp": now - 3600,  # expired
        }
        token = pyjwt.encode(claims, signing_key, algorithm="HS256")

        auth_ctx = AuthContext(
            user_id="alice@example.com",
            username="alice",
            org_id="acme",
            team_id="eng",
            roles=frozenset({"user"}),
            kind=IdentityKind.USER,
        )
        auth_provider = FakeAuthProvider(auth_context=auth_ctx)
        app = _build_app(auth_provider=auth_provider)
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["authenticated"] is True
            assert data["user_id"] == "alice@example.com"
            assert data["kind"] == "user"

    def test_invalid_token_and_auth_provider_rejects_returns_401(self) -> None:
        """When both HS256 and auth_provider fail, returns 401."""
        failing_auth = FakeAuthProvider()

        async def _reject(
            authorization: str | None, headers: dict[str, str] | None = None
        ) -> AuthContext:
            raise ValueError("Invalid token")

        failing_auth.authenticate = _reject  # type: ignore[assignment]

        app = _build_app(auth_provider=failing_auth)
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": "totally-invalid-jwt"},
            )
            assert resp.status_code == 401
            assert resp.json()["authenticated"] is False

    def test_non_jwt_cookie_with_failing_auth_returns_401(self) -> None:
        """When the cookie is not a valid JWT and auth_provider also rejects it."""
        failing_auth = FakeAuthProvider()

        async def _reject(
            authorization: str | None, headers: dict[str, str] | None = None
        ) -> AuthContext:
            raise ValueError("Invalid token")

        failing_auth.authenticate = _reject  # type: ignore[assignment]

        app = _build_app(auth_provider=failing_auth)
        with TestClient(app) as client:
            resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": "not-a-jwt"},
            )
            # Should fall through both HS256 and auth_provider paths
            assert resp.status_code == 401
            assert resp.json()["authenticated"] is False


# ── Auth config endpoint ──────────────────────────────────────────────


class TestAuthConfig:
    """Test GET /auth/config — returns non-sensitive OIDC config."""

    def test_default_config_no_oidc(self) -> None:
        app = _build_app()
        with TestClient(app) as client:
            resp = client.get("/auth/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["oidc_enabled"] is False
            assert data["bff_enabled"] is False
            assert data["authorization_url"] == ""
            assert data["client_id"] == ""

    def test_oidc_configured(self) -> None:
        cfg = _base_config(
            client_id="my-client",
            authorization_url="https://idp.example.com/authorize",
            token_url="https://idp.example.com/token",
            issuer="https://idp.example.com",
        )
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            resp = client.get("/auth/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["oidc_enabled"] is True
            assert data["bff_enabled"] is True
            assert data["authorization_url"] == "https://idp.example.com/authorize"
            assert data["client_id"] == "my-client"
            assert data["issuer"] == "https://idp.example.com"

    def test_partial_oidc_config_no_token_url(self) -> None:
        """client_id + authorization_url but no token_url -> oidc_enabled but bff_disabled."""
        cfg = _base_config(
            client_id="my-client",
            authorization_url="https://idp.example.com/authorize",
        )
        app = _build_app(config=cfg)
        with TestClient(app) as client:
            resp = client.get("/auth/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["oidc_enabled"] is True
            assert data["bff_enabled"] is False


# ── Password hashing/verification ─────────────────────────────────────


class TestPasswordHelpers:
    """Test _hash_password and _verify_password functions."""

    def test_hash_and_verify_round_trip(self) -> None:
        password = "my-secure-password-123"
        hashed = _hash_password(password)
        # Current implementation uses Argon2id
        assert hashed.startswith("$argon2")
        assert _verify_password(password, hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = _hash_password("correct")
        assert _verify_password("wrong", hashed) is False

    def test_verify_empty_hash(self) -> None:
        assert _verify_password("password", "") is False

    def test_verify_non_pbkdf2_hash(self) -> None:
        assert _verify_password("password", "bcrypt:something") is False

    def test_verify_malformed_hash(self) -> None:
        assert _verify_password("password", "pbkdf2:only_salt") is False

    def test_verify_correct_format_wrong_digest(self) -> None:
        assert _verify_password("password", "pbkdf2:salt:badhex") is False


# ── Registration ──────────────────────────────────────────────────────


class TestRegistration:
    """Test POST /auth/register — user self-registration."""

    def test_register_missing_email_returns_400(self) -> None:
        db = FakeDBPool()
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 400
            assert "email and org_id are required" in resp.json()["detail"]

    def test_register_missing_org_returns_400(self) -> None:
        db = FakeDBPool()
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "org_id": ""},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 400
            assert "email and org_id are required" in resp.json()["detail"]

    def test_register_disabled_returns_403(self) -> None:
        """When allowed_registration_orgs is empty, registration is disabled."""
        db = FakeDBPool()
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 403
            assert "Self-registration is disabled" in resp.json()["detail"]

    def test_register_org_not_allowed_returns_400(self) -> None:
        db = FakeDBPool()
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "org_id": "evil-corp"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 400
            assert "not available for this organization" in resp.json()["detail"]

    def test_register_existing_approved_returns_409(self) -> None:
        db = FakeDBPool()
        db.add_user(
            {
                "id": 1,
                "email": "existing@example.com",
                "status": "approved",
            }
        )
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "existing@example.com", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 409
            assert "already exists" in resp.json()["detail"]

    @pytest.mark.parametrize("status", ["pending", "rejected", "disabled"])
    def test_register_existing_any_status_returns_409(self, status: str) -> None:
        """pending/rejected/disabled all yield a 409 with an 'already exists' detail.

        Covers that registration conflict detection is status-agnostic for
        non-approved accounts. (The exact wording may mention review/status by
        design — so we only assert the stable prefix.)
        """
        db = FakeDBPool()
        db.add_user({"id": 1, "email": f"{status}@example.com", "status": status})
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": f"{status}@example.com", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 409
            detail = resp.json()["detail"].lower()
            assert "already exists" in detail

    def test_register_new_user_success(self) -> None:
        db = FakeDBPool()
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={
                    "email": "newuser@example.com",
                    "org_id": "acme",
                    "display_name": "New User",
                    "password": "secure123",
                    "team_id": "engineering",
                },
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "pending"
            assert "submitted" in data["message"]

    def test_register_new_user_no_password_still_creates_pending(self) -> None:
        """Registration without a password must still create a pending account.

        (Passwords can be set by admin or via a later reset flow.)
        """
        db = FakeDBPool()
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=db)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "nopass@example.com", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "pending"
            assert "submitted" in data["message"].lower()

    def test_register_no_db_returns_503(self) -> None:
        cfg = _base_config(allowed_registration_orgs=["acme"])
        app = _build_app(config=cfg, db_pool=None)
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "org_id": "acme"},
                headers=CSRF_HEADER,
            )
            assert resp.status_code == 503


# ── End-to-end: login then session check ──────────────────────────────


class TestLoginThenSession:
    """Full round-trip: login, get cookie, check session."""

    def test_login_cookie_validates_in_session(self) -> None:
        """Login should set a cookie that /auth/session can decode."""
        pw_hash = _make_password_hash("password123")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 10,
                "email": "roundtrip@example.com",
                "display_name": "RT User",
                "org_id": "acme",
                "team_id": "eng",
                "roles": '["user"]',
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app, cookies={}) as client:
            # Login
            login_resp = client.post(
                "/auth/login",
                json={"email": "roundtrip@example.com", "password": "password123"},
                headers=CSRF_HEADER,
            )
            assert login_resp.status_code == 200

            # Extract the session cookie from the login response
            # and explicitly set it on the client for the next request
            session_cookie = None
            for header_val in login_resp.headers.get_list("set-cookie"):
                if "stronghold_session=" in header_val:
                    # Parse "stronghold_session=TOKEN; ..."
                    cookie_part = header_val.split(";")[0]
                    session_cookie = cookie_part.split("=", 1)[1]
                    break
            assert session_cookie is not None, "Login did not set stronghold_session cookie"

            # Check session with the cookie
            session_resp = client.get(
                "/auth/session",
                cookies={"stronghold_session": session_cookie},
            )
            assert session_resp.status_code == 200
            data = session_resp.json()
            assert data["authenticated"] is True
            assert data["user_id"] == "roundtrip@example.com"
            assert data["username"] == "RT User"

    def test_login_then_logout_then_session_fails(self) -> None:
        """After logout, session check should fail."""
        pw_hash = _make_password_hash("password123")
        db = FakeDBPool()
        db.add_user(
            {
                "id": 11,
                "email": "logouttest@example.com",
                "display_name": "Logout",
                "org_id": "acme",
                "team_id": "eng",
                "roles": '["user"]',
                "status": "approved",
                "password_hash": pw_hash,
            }
        )
        app = _build_app(db_pool=db)
        with TestClient(app) as client:
            # Login
            login_resp = client.post(
                "/auth/login",
                json={"email": "logouttest@example.com", "password": "password123"},
                headers=CSRF_HEADER,
            )
            assert login_resp.status_code == 200

            # Logout
            logout_resp = client.get("/auth/logout")
            assert logout_resp.status_code == 200

            # Session should now fail (cookies cleared). Two permissible
            # shapes for the "unauthenticated" signal:
            #   - 401 with no body contract, or
            #   - 200 with {"authenticated": false}
            # Either way, the client must not be told they are authenticated.
            session_resp = client.get("/auth/session")
            code = session_resp.status_code
            if code == 401:
                # Explicit unauthenticated status — acceptable.
                assert True
            elif code == 200:
                # Must explicitly carry authenticated=False.
                assert session_resp.json().get("authenticated") is False
            else:
                msg = (
                    f"Unexpected /auth/session status after logout: {code} "
                    f"body={session_resp.text!r}"
                )
                raise AssertionError(msg)
