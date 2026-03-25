"""Cookie-based authentication provider (BFF pattern).

Extracts a JWT from an HttpOnly session cookie and delegates validation
to the JWTAuthProvider. This keeps tokens out of JavaScript entirely —
the browser sends the cookie automatically, and the token is never
accessible to client-side code.

Security properties:
  - HttpOnly: JS cannot read the token (XSS-proof)
  - Secure: cookie only sent over HTTPS
  - SameSite=Lax: mitigates CSRF for GET, POST requires same-site origin
  - Defense-in-depth: state-changing routes should also check
    X-Stronghold-Request header (custom headers require CORS preflight,
    blocking cross-origin form POSTs)
"""

from __future__ import annotations

import logging
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.security.auth_jwt import JWTAuthProvider
    from stronghold.types.auth import AuthContext

logger = logging.getLogger("stronghold.auth.cookie")


class CookieAuthProvider:
    """Authenticates via HttpOnly session cookie containing a JWT."""

    def __init__(
        self,
        *,
        jwt_provider: JWTAuthProvider,
        cookie_name: str = "stronghold_session",
    ) -> None:
        self._jwt = jwt_provider
        self._cookie_name = cookie_name

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Extract JWT from cookie and validate via the JWT provider.

        Raises ValueError if no cookie or JWT validation fails.
        """
        if not headers:
            msg = "No headers provided (cookie auth requires headers)"
            raise ValueError(msg)

        cookie_header = headers.get("cookie", "")
        if not cookie_header:
            msg = "No cookie header present"
            raise ValueError(msg)

        token = self._extract_cookie(cookie_header)
        if not token:
            msg = f"Cookie '{self._cookie_name}' not found"
            raise ValueError(msg)

        # Delegate to JWT provider — same validation as Bearer tokens
        ctx = await self._jwt.authenticate(f"Bearer {token}", headers=headers)

        logger.debug("Cookie auth succeeded for user=%s", ctx.user_id)
        return ctx

    def _extract_cookie(self, cookie_header: str) -> str:
        """Parse a Cookie header and extract the session token.

        Uses stdlib SimpleCookie for correct parsing of quoted values,
        multi-value cookies, and edge cases.
        """
        try:
            sc: SimpleCookie = SimpleCookie()
            sc.load(cookie_header)
            morsel = sc.get(self._cookie_name)
            if morsel is not None:
                return str(morsel.value)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to parse cookie header")
        return ""
