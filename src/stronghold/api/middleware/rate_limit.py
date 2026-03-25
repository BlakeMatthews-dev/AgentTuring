"""Rate limiting middleware.

Extracts a rate-limit key from the request (user_id from auth, or client IP)
and enforces per-key request limits. Returns 429 Too Many Requests with
Retry-After header when the limit is exceeded.

Runs AFTER auth middleware so it can use the authenticated identity.
For unauthenticated requests (health check, OPTIONS), uses client IP.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from stronghold.security.rate_limiter import InMemoryRateLimiter

logger = logging.getLogger("stronghold.middleware.rate_limit")

# Endpoints exempt from rate limiting
_EXEMPT_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc"})
_EXEMPT_PREFIXES = (
    "/login/callback",  # OIDC callback (not the login action itself)
    "/auth/session",  # Session check (read-only, frequent)
    "/auth/config",  # Public OIDC config (read-only)
    "/auth/logout",  # Logout (no brute force risk)
    # /auth/login and /auth/register are NOT exempt — brute force protection
    "/dashboard/",  # Static dashboard pages + JS assets
    "/greathall",  # Main dashboard
    "/prompts",  # Prompts page
)
# Exact-match exempt paths (these need rate limiting on POST but not GET)
_EXEMPT_EXACT = frozenset({"/login"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-user rate limiting middleware."""

    def __init__(self, app: Any, rate_limiter: InMemoryRateLimiter) -> None:
        super().__init__(app)
        self._limiter = rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        # Skip rate limiting for exempt paths, prefixes, and OPTIONS
        path = request.url.path
        if path in _EXEMPT_PATHS or request.method == "OPTIONS":
            result: Response = await call_next(request)
            return result
        if (
            any(path.startswith(p) for p in _EXEMPT_PREFIXES)
            or path == "/"
            or path in _EXEMPT_EXACT
        ):
            result = await call_next(request)
            return result

        # Extract key: prefer auth user_id, fall back to client IP
        key = self._extract_key(request)

        # Check rate limit
        allowed, headers = await self._limiter.check(key)

        if not allowed:
            reset = headers.get("X-RateLimit-Reset", "60")
            resp = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Rate limit exceeded. Try again later.",
                        "type": "rate_limit_error",
                        "code": "RATE_LIMITED",
                    }
                },
                headers={**headers, "Retry-After": reset},
            )
            return resp

        # Record the request and proceed
        await self._limiter.record(key)
        response: Response = await call_next(request)

        # Add rate limit headers to successful responses
        for k, v in headers.items():
            response.headers[k] = v

        return response

    @staticmethod
    def _extract_key(request: Request) -> str:
        """Extract rate limit key from request.

        Priority: Authorization header hash > OpenWebUI user ID > client IP.
        """
        # Try OpenWebUI user header
        owui_id = request.headers.get("x-openwebui-user-id")
        if owui_id:
            return f"user:{owui_id}"

        # Try auth header (hash to avoid storing full token)
        auth = request.headers.get("authorization", "")
        if auth:
            import hashlib  # noqa: PLC0415

            return f"auth:{hashlib.sha256(auth.encode()).hexdigest()[:16]}"

        # Fall back to client IP
        client = request.client
        ip = client.host if client else "unknown"
        return f"ip:{ip}"
