"""Security headers middleware.

Adds production security headers to all responses:
- Strict-Transport-Security (HSTS)
- X-Frame-Options (clickjacking protection)
- X-Content-Type-Options (MIME sniffing prevention)
- Referrer-Policy (privacy)
- Permissions-Policy (browser feature restrictions)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        """Add security headers to the response."""
        response: Response = await call_next(request)

        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
