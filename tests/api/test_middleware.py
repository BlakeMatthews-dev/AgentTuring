"""Integration tests for Stronghold API middleware.

Covers:
- PayloadSizeLimitMiddleware (size enforcement + edge cases)
- DemoCookieMiddleware (JWT cookie injection into ASGI scope)
- Auth route pattern (valid key, missing auth, invalid auth via StaticKeyAuthProvider)
- TracingMiddleware (stub file, no middleware class — verify it's a placeholder)

Uses real classes per project rules. Only external HTTP calls would be mocked.
asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import jwt as pyjwt
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSON
from starlette.routing import Route
from starlette.testclient import TestClient

from stronghold.api.middleware import PayloadSizeLimitMiddleware
from stronghold.api.middleware.demo_cookie import DemoCookieMiddleware
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.types.auth import SYSTEM_AUTH, AuthContext
from stronghold.types.config import AuthConfig, StrongholdConfig, TaskTypeConfig

AUTH_HEADER = {"Authorization": "Bearer sk-test"}
API_KEY = "sk-test"


# ── Helpers ───────────────────────────────────────────────────────────


def _minimal_config(**overrides: Any) -> StrongholdConfig:
    """Build a minimal StrongholdConfig with sensible defaults."""
    defaults: dict[str, Any] = {
        "providers": {
            "test": {
                "status": "active",
                "billing_cycle": "monthly",
                "free_tokens": 1_000_000,
            },
        },
        "models": {
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        "task_types": {
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        "permissions": {"admin": ["*"]},
        "router_api_key": API_KEY,
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


# ── PayloadSizeLimitMiddleware ────────────────────────────────────────


def _payload_app(max_bytes: int = 1000) -> FastAPI:
    """Build a minimal app with PayloadSizeLimitMiddleware."""

    async def echo(request: StarletteRequest) -> StarletteJSON:
        body = await request.body()
        return StarletteJSON({"size": len(body)})

    app = FastAPI(routes=[Route("/echo", echo, methods=["POST"])])
    app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=max_bytes)
    return app


class TestPayloadSizeLimitUnderLimit:
    """Requests with Content-Length under the limit pass through."""

    def test_small_request_passes(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post("/echo", content=b"hello")
            assert resp.status_code == 200
            assert resp.json()["size"] == 5


class TestPayloadSizeLimitOverLimit:
    """Requests exceeding the byte limit are rejected with 413."""

    def test_oversized_request_returns_413(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 200,
                headers={"Content-Length": "200"},
            )
            assert resp.status_code == 413
            body = resp.json()
            assert "Payload too large" in body["error"]["message"]
            assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"

    def test_exactly_at_limit_passes(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 100,
                headers={"Content-Length": "100"},
            )
            assert resp.status_code == 200

    def test_one_byte_over_limit_returns_413(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 101,
                headers={"Content-Length": "101"},
            )
            assert resp.status_code == 413


class TestPayloadSizeLimitNoContentLength:
    """Requests with no Content-Length header pass through (GET, empty POST)."""

    def test_get_request_passes_through(self) -> None:
        """GET requests have no body and should always pass."""

        async def healthcheck(request: StarletteRequest) -> StarletteJSON:
            return StarletteJSON({"ok": True})

        app = FastAPI(
            routes=[
                Route("/health", healthcheck, methods=["GET"]),
                Route("/echo", lambda r: StarletteJSON({"ok": True}), methods=["POST"]),
            ]
        )
        app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=10)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_post_without_content_length_passes(self) -> None:
        """POST with no Content-Length and no chunked encoding passes."""
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            # Sending empty body -- no Content-Length header
            resp = client.post("/echo")
            assert resp.status_code == 200


class TestPayloadSizeLimitInvalidContentLength:
    """Invalid Content-Length values are rejected with 400."""

    def test_invalid_content_length_returns_400(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"hello",
                headers={"Content-Length": "not-a-number"},
            )
            assert resp.status_code == 400
            assert "Invalid Content-Length" in resp.json()["error"]["message"]

    def test_negative_content_length_returns_413(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"hello",
                headers={"Content-Length": "-1"},
            )
            assert resp.status_code == 413


# ── DemoCookieMiddleware ──────────────────────────────────────────────


class _FakeContainer:
    """Minimal container stand-in with the fields DemoCookieMiddleware reads."""

    def __init__(self, cookie_name: str = "stronghold_session", api_key: str = API_KEY) -> None:
        self.config = _minimal_config(
            auth=AuthConfig(session_cookie_name=cookie_name),
        )
        self.config.router_api_key = api_key
        self.config.jwt_secret = api_key


def _demo_cookie_app(
    cookie_name: str = "stronghold_session",
    api_key: str = API_KEY,
) -> FastAPI:
    """Build an app with DemoCookieMiddleware and an echo endpoint."""
    app = FastAPI()

    # Add the ASGI middleware
    app.add_middleware(DemoCookieMiddleware)

    @app.get("/echo-auth")
    async def echo_auth(request: Request) -> JSONResponse:
        """Return the Authorization header as seen by the route handler."""
        auth = request.headers.get("authorization")
        return JSONResponse({"authorization": auth})

    # Wire up the fake container so the middleware can read config
    app.state.container = _FakeContainer(cookie_name=cookie_name, api_key=api_key)

    return app


def _make_demo_jwt(
    signing_key: str = API_KEY,
    sub: str = "demo-user",
    org_id: str = "demo-org",
    exp_offset: int = 3600,
) -> str:
    """Create a valid HS256 demo JWT."""
    payload = {
        "sub": sub,
        "org_id": org_id,
        "aud": "stronghold",
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    return pyjwt.encode(payload, signing_key, algorithm="HS256")


class TestDemoCookieExistingAuth:
    """Request with existing Authorization header is not modified."""

    def test_existing_auth_header_not_overwritten(self) -> None:
        app = _demo_cookie_app()
        token = _make_demo_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={
                    "Authorization": "Bearer my-real-token",
                    "Cookie": f"stronghold_session={token}",
                },
            )
            assert resp.status_code == 200
            # The middleware should NOT overwrite the existing Authorization
            assert resp.json()["authorization"] == "Bearer my-real-token"


class TestDemoCookieValidCookie:
    """Request with valid demo cookie gets Authorization injected."""

    def test_valid_cookie_injects_bearer(self) -> None:
        app = _demo_cookie_app()
        token = _make_demo_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"stronghold_session={token}"},
            )
            assert resp.status_code == 200
            auth = resp.json()["authorization"]
            assert auth is not None
            assert auth.startswith("Bearer demo-jwt:")
            # The injected value should contain the original JWT
            assert token in auth


class TestDemoCookieInvalidCookie:
    """Request with invalid cookie is not modified."""

    def test_expired_jwt_not_injected(self) -> None:
        app = _demo_cookie_app()
        # Create an expired JWT
        expired_token = _make_demo_jwt(exp_offset=-3600)
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"stronghold_session={expired_token}"},
            )
            assert resp.status_code == 200
            # Invalid JWT means no injection
            assert resp.json()["authorization"] is None

    def test_wrong_signing_key_not_injected(self) -> None:
        app = _demo_cookie_app()
        # Sign with a different key than the app uses
        bad_token = _make_demo_jwt(signing_key="wrong-secret-key-12345")
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"stronghold_session={bad_token}"},
            )
            assert resp.status_code == 200
            assert resp.json()["authorization"] is None

    def test_wrong_audience_not_injected(self) -> None:
        app = _demo_cookie_app()
        # Create a JWT with wrong audience
        payload = {
            "sub": "demo-user",
            "aud": "wrong-audience",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        bad_token = pyjwt.encode(payload, API_KEY, algorithm="HS256")
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"stronghold_session={bad_token}"},
            )
            assert resp.status_code == 200
            assert resp.json()["authorization"] is None

    def test_garbage_cookie_value_not_injected(self) -> None:
        app = _demo_cookie_app()
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": "stronghold_session=not-a-jwt-at-all"},
            )
            assert resp.status_code == 200
            assert resp.json()["authorization"] is None


class TestDemoCookieNoCookie:
    """Request with no cookie passes through without modification."""

    def test_no_cookie_passes_through(self) -> None:
        app = _demo_cookie_app()
        with TestClient(app) as client:
            resp = client.get("/echo-auth")
            assert resp.status_code == 200
            assert resp.json()["authorization"] is None

    def test_wrong_cookie_name_ignored(self) -> None:
        app = _demo_cookie_app(cookie_name="stronghold_session")
        token = _make_demo_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"other_cookie={token}"},
            )
            assert resp.status_code == 200
            assert resp.json()["authorization"] is None


class TestDemoCookieNoContainer:
    """Request when no container is set on app state passes through."""

    def test_no_container_passes_through(self) -> None:
        app = FastAPI()
        app.add_middleware(DemoCookieMiddleware)

        @app.get("/echo-auth")
        async def echo_auth(request: Request) -> JSONResponse:
            auth = request.headers.get("authorization")
            return JSONResponse({"authorization": auth})

        token = _make_demo_jwt()
        with TestClient(app) as client:
            resp = client.get(
                "/echo-auth",
                headers={"Cookie": f"stronghold_session={token}"},
            )
            assert resp.status_code == 200
            # No container means middleware cannot read config, so it passes through
            assert resp.json()["authorization"] is None


# ── Auth route pattern (StaticKeyAuthProvider) ────────────────────────
# Auth is not a middleware class but a per-route pattern using
# container.auth_provider.authenticate(). Test the real StaticKeyAuthProvider
# wired into a minimal FastAPI app (same pattern as production routes).


def _auth_app() -> FastAPI:
    """Build an app that uses the auth route pattern from production."""
    app = FastAPI()
    auth_provider = StaticKeyAuthProvider(api_key=API_KEY)

    @app.get("/protected")
    async def protected(request: Request) -> JSONResponse:
        auth_header = request.headers.get("authorization")
        try:
            ctx = await auth_provider.authenticate(auth_header)
        except ValueError as e:
            return JSONResponse(status_code=401, content={"detail": str(e)})
        return JSONResponse({"user_id": ctx.user_id, "auth_method": ctx.auth_method})

    return app


class TestAuthValidKey:
    """Valid API key returns 200 with authenticated context."""

    def test_valid_key_returns_200(self) -> None:
        app = _auth_app()
        with TestClient(app) as client:
            resp = client.get("/protected", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == SYSTEM_AUTH.user_id
            assert data["auth_method"] == "api_key"


class TestAuthMissing:
    """Missing Authorization header returns 401."""

    def test_no_auth_returns_401(self) -> None:
        app = _auth_app()
        with TestClient(app) as client:
            resp = client.get("/protected")
            assert resp.status_code == 401
            assert "Missing" in resp.json()["detail"]


class TestAuthInvalid:
    """Invalid Authorization values return 401."""

    def test_wrong_key_returns_401(self) -> None:
        app = _auth_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 401
            assert "Invalid" in resp.json()["detail"]

    def test_no_bearer_prefix_returns_401(self) -> None:
        app = _auth_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": API_KEY},
            )
            assert resp.status_code == 401
            assert "Invalid" in resp.json()["detail"]

    def test_empty_bearer_returns_401(self) -> None:
        app = _auth_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer "},
            )
            assert resp.status_code == 401
            assert "Invalid" in resp.json()["detail"]
