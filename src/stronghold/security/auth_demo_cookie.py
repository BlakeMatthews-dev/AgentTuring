"""Demo cookie authentication provider.

Validates HS256 JWTs signed with the router API key.
Accepts tokens from two sources:
  1. Authorization header: "Bearer demo-jwt:<token>" (injected by middleware)
  2. Session cookie (direct cookie reads, when headers are passed)
"""

from __future__ import annotations

from http.cookies import SimpleCookie

import jwt as pyjwt

from stronghold.types.auth import AuthContext, IdentityKind

_PREFIX = "Bearer demo-jwt:"


_MIN_KEY_LENGTH = 32
_logger = __import__("logging").getLogger("stronghold.auth.demo_cookie")


class DemoCookieAuthProvider:
    """Authenticates via HS256 JWT from middleware-injected header or cookie.

    H5: This provider uses symmetric HS256 signing with the router API key.
    In production, configure JWKS_URL to enable RS256 JWT auth, which takes
    priority in the composite auth chain. The demo cookie provider is then
    only used for the built-in login page flow.
    """

    def __init__(self, api_key: str, cookie_name: str = "stronghold_session") -> None:
        if len(api_key) < _MIN_KEY_LENGTH:
            _logger.warning(
                "DemoCookieAuthProvider: API key is %d bytes, minimum recommended "
                "is %d for HS256 security. Set a longer ROUTER_API_KEY.",
                len(api_key),
                _MIN_KEY_LENGTH,
            )
        self._key = api_key
        self._cookie_name = cookie_name

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        token: str = ""

        # Source 1: middleware-injected header (preferred — already validated format)
        if authorization and authorization.startswith(_PREFIX):
            token = authorization[len(_PREFIX) :]

        # Source 2: direct cookie read
        if not token and headers:
            cookie_header = headers.get("cookie", "")
            if cookie_header:
                sc: SimpleCookie = SimpleCookie()
                try:
                    sc.load(cookie_header)
                except Exception:  # noqa: BLE001  # nosec B110 - malformed cookie treated as absent
                    pass
                else:
                    morsel = sc.get(self._cookie_name)
                    if morsel and morsel.value:
                        token = morsel.value

        if not token:
            msg = "No demo session token"
            raise ValueError(msg)

        try:
            claims = pyjwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience="stronghold",
                issuer="stronghold-demo",
            )
        except pyjwt.PyJWTError as e:
            msg = f"Invalid demo session: {e}"
            raise ValueError(msg) from e

        roles_raw = claims.get("roles", [])
        roles = frozenset(roles_raw) if isinstance(roles_raw, list) else frozenset()

        return AuthContext(
            user_id=claims.get("sub", ""),
            username=claims.get("preferred_username", ""),
            roles=roles,
            org_id=claims.get("organization_id", ""),
            team_id=claims.get("team_id", ""),
            kind=IdentityKind.USER,
            auth_method="demo_cookie",
        )
