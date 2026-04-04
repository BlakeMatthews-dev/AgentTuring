"""Middleware: inject Authorization header from demo session cookie.

Pure ASGI middleware (not BaseHTTPMiddleware) so that scope["headers"]
is modified BEFORE Starlette constructs the Request object. This ensures
request.headers.get("authorization") sees the injected header in all
downstream route handlers.
"""

from __future__ import annotations

import logging

from http.cookies import SimpleCookie
from typing import TYPE_CHECKING

import jwt as pyjwt

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class DemoCookieMiddleware:
    """Extract demo JWT from session cookie, inject auth header into ASGI scope."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", [])

        # Check if Authorization header already present
        has_auth = any(k == b"authorization" for k, _ in raw_headers)
        if has_auth:
            await self.app(scope, receive, send)
            return

        # Extract cookie header
        cookie_val = ""
        for k, v in raw_headers:
            if k == b"cookie":
                cookie_val = v.decode("latin-1")
                break

        if not cookie_val:
            await self.app(scope, receive, send)
            return

        # Get config from app state (set during lifespan startup)
        app = scope.get("app")
        container = getattr(getattr(app, "state", None), "container", None)
        if not container:
            await self.app(scope, receive, send)
            return

        cookie_name = container.config.auth.session_cookie_name
        signing_key = container.config.router_api_key

        sc: SimpleCookie = SimpleCookie()
        try:
            sc.load(cookie_val)
        except Exception:  # noqa: BLE001
            await self.app(scope, receive, send)
            return

        morsel = sc.get(cookie_name)
        if not morsel or not morsel.value:
            logger.debug(
                "CookieMiddleware extracted: cookie_name=%s found=%s",
                cookie_name,
                bool(morsel),
            )
            await self.app(scope, receive, send)
            return

        # Validate HS256 demo JWT
        try:
            pyjwt.decode(
                morsel.value,
                signing_key,
                algorithms=["HS256"],
                audience="stronghold",
            )
        except pyjwt.PyJWTError:
            await self.app(scope, receive, send)
            return

        # Valid demo session — inject the user's JWT as Authorization Bearer.
        # The DemoCookieAuthProvider in the composite chain will decode it
        # and extract per-user claims (sub, org_id, team_id, roles).
        # CRITICAL: inject the JWT, NOT the raw API key. The API key would
        # grant SYSTEM_AUTH and discard the user's identity.
        new_headers = list(raw_headers)
        new_headers.append((b"authorization", f"Bearer demo-jwt:{morsel.value}".encode()))
        scope["headers"] = new_headers

        await self.app(scope, receive, send)
