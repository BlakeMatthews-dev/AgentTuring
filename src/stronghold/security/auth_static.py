"""Static API key authentication provider.

Also extracts OpenWebUI user context from X-OpenWebUI-User-* headers
when present, building a richer AuthContext than the default SYSTEM_AUTH.
"""

from __future__ import annotations

import hmac

from stronghold.types.auth import SYSTEM_AUTH, AuthContext, IdentityKind


class StaticKeyAuthProvider:
    """Authenticates via static API key. Extracts OpenWebUI user headers."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Validate Bearer token against static key.

        If OpenWebUI user headers are present, builds a user-scoped
        AuthContext instead of returning SYSTEM_AUTH.
        Uses constant-time comparison to prevent timing attacks.
        """
        if not authorization:
            msg = "Missing Authorization header"
            raise ValueError(msg)

        if not authorization.startswith("Bearer "):
            msg = "Invalid authorization format"
            raise ValueError(msg)

        token = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, self._api_key):
            msg = "Invalid API key"
            raise ValueError(msg)

        # Extract OpenWebUI user context if headers present
        if headers:
            owui_ctx = _extract_openwebui_context(headers)
            if owui_ctx:
                return owui_ctx

        return SYSTEM_AUTH


def _extract_openwebui_context(headers: dict[str, str]) -> AuthContext | None:
    """Extract user identity from OpenWebUI forwarded headers.

    OpenWebUI sends:
    - X-OpenWebUI-User-Email
    - X-OpenWebUI-User-Name
    - X-OpenWebUI-User-Id
    - X-OpenWebUI-User-Role

    Returns AuthContext if any user identity header is present, else None.
    """
    email = headers.get("x-openwebui-user-email", "")
    name = headers.get("x-openwebui-user-name", "")
    user_id = headers.get("x-openwebui-user-id", "")

    if not (email or user_id):
        return None

    # Never trust role from headers — always restrict to "user".
    # Admin roles must be granted via JWT claims or server-side config.
    roles = frozenset({"user"})

    return AuthContext(
        user_id=user_id or email,
        username=name or email,
        roles=roles,
        org_id="openwebui",
        kind=IdentityKind.USER,
        auth_method="openwebui_header",
    )
