"""JWT authentication provider — IdP-agnostic (Keycloak, Entra ID, Auth0, Okta).

Validates RS256/RS384/RS512 JWTs against a JWKS endpoint.
Extracts user identity, roles, org_id, and team_id from token claims.
Mirrors LiteLLM's organization model: organization_id + team_id on keys.
JWKS keys are cached with a configurable TTL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from stronghold.types.auth import AuthContext, IdentityKind

logger = logging.getLogger("stronghold.auth.jwt")


class JWTAuthProvider:
    """Authenticates via JWT tokens from any OIDC-compliant IdP.

    Configuration:
        jwks_url: JWKS endpoint (e.g., https://sso.example.com/realms/X/protocol/openid-connect/certs)
        issuer: Expected issuer claim (e.g., https://sso.example.com/realms/X)
        audience: Expected audience claim (e.g., "stronghold-api")
        role_claim: JSON path to roles in token (default: "realm_access.roles" for Keycloak)
        org_claim: JSON path to organization_id (default: "organization_id", mirrors LiteLLM)
        team_claim: JSON path to team_id (default: "team_id", mirrors LiteLLM)
        kind_claim: JSON path to identity kind (default: "kind")
        require_org: If True, reject tokens without org_id (multi-tenant mode)
        jwks_cache_ttl: Seconds to cache JWKS keys (default: 3600)
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        role_claim: str = "realm_access.roles",
        org_claim: str = "organization_id",
        team_claim: str = "team_id",
        kind_claim: str = "kind",
        require_org: bool = False,
        jwks_cache_ttl: int = 3600,
        jwt_decode: Any = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience
        self._role_claim = role_claim
        self._org_claim = org_claim
        self._team_claim = team_claim
        self._kind_claim = kind_claim
        self._require_org = require_org
        self._jwks_cache_ttl = jwks_cache_ttl
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_at: float = 0.0
        self._cache_lock = asyncio.Lock()
        # Injectable JWT decoder for testing (avoids importing PyJWT at module level)
        self._jwt_decode = jwt_decode

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Validate JWT and extract identity.

        Raises ValueError on invalid/expired/missing tokens.
        """
        if not authorization:
            msg = "Missing Authorization header"
            raise ValueError(msg)

        if not authorization.startswith("Bearer "):
            msg = "Invalid authorization format"
            raise ValueError(msg)

        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            msg = "Empty token"
            raise ValueError(msg)

        # Decode and validate
        claims = await self._decode_token(token)

        # Extract identity
        user_id = claims.get("sub", "")
        username = claims.get("preferred_username", claims.get("name", user_id))
        roles = self._extract_roles(claims)

        # Organization + Team (mirrors LiteLLM key model)
        org_id_raw = self._extract_nested(claims, self._org_claim)
        team_id_raw = self._extract_nested(claims, self._team_claim)
        kind_raw = self._extract_nested(claims, self._kind_claim)

        org_id = str(org_id_raw) if org_id_raw else ""
        team_id = str(team_id_raw) if team_id_raw else ""

        # Determine identity kind from token claim
        kind = IdentityKind.USER
        if kind_raw == "service_account":
            kind = IdentityKind.SERVICE_ACCOUNT
        elif kind_raw == "interactive_agent":
            kind = IdentityKind.INTERACTIVE_AGENT
        elif kind_raw == "agent":
            kind = IdentityKind.AGENT

        if not user_id:
            msg = "Token missing 'sub' claim"
            raise ValueError(msg)

        if self._require_org and not org_id:
            msg = "Token missing organization_id claim (multi-tenant mode requires it)"
            raise ValueError(msg)

        # Extract on_behalf_of for interactive agents
        on_behalf_of = ""
        if kind == IdentityKind.INTERACTIVE_AGENT:
            obo_raw = self._extract_nested(claims, "on_behalf_of")
            on_behalf_of = str(obo_raw) if obo_raw else ""
            # Security: on_behalf_of must not contain a different org prefix.
            # Full user validation requires a user registry (enforced in Sentinel),
            # but we can reject obvious cross-org forgery here.
            if on_behalf_of and "/" in on_behalf_of:
                obo_org = on_behalf_of.split("/")[0]
                if org_id and obo_org != org_id:
                    msg = f"on_behalf_of org mismatch: {obo_org} != {org_id}"
                    raise ValueError(msg)

        return AuthContext(
            user_id=str(user_id),
            username=str(username),
            roles=frozenset(str(r) for r in roles),
            org_id=org_id,
            team_id=team_id,
            kind=kind,
            auth_method="jwt",
            on_behalf_of=on_behalf_of,
        )

    async def _decode_token(self, token: str) -> dict[str, Any]:
        """Decode and validate JWT against JWKS."""
        if self._jwt_decode is not None:
            # Injected decoder for testing
            return dict(self._jwt_decode(token))

        try:
            import jwt as pyjwt  # noqa: PLC0415
            from jwt import PyJWKClient  # noqa: PLC0415
        except ImportError:
            msg = "PyJWT with cryptography is required: pip install PyJWT[crypto]"
            raise ValueError(msg)  # noqa: B904

        # Fetch JWKS with caching
        jwks_client = await self._get_jwks_client(pyjwt, PyJWKClient)

        return await self._decode_token_with_client(token, pyjwt, jwks_client)

    async def _decode_token_with_client(
        self, token: str, pyjwt: Any, jwks_client: Any
    ) -> dict[str, Any]:
        """Decode JWT using the given JWKS client. Runs blocking I/O in a thread."""

        def _blocking_decode() -> dict[str, Any]:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            decoded: dict[str, Any] = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512"],
                issuer=self._issuer,
                audience=self._audience,
            )
            return decoded

        try:
            return await asyncio.to_thread(_blocking_decode)
        except Exception as e:
            msg = f"JWT validation failed: {e}"
            raise ValueError(msg) from e

    async def _get_jwks_client(self, pyjwt: Any, jwk_client_cls: type) -> Any:
        """Get JWKS client with TTL-based caching.

        Uses asyncio.Lock to serialize refreshes. If the cache is expired,
        exactly one task refreshes while others wait (and then see the new cache).
        Stale cache is used as fallback if the refresh fails.
        """
        # Fast path: check without lock (immutable read of cache + timestamp)
        now = time.monotonic()
        if self._jwks_cache is not None and (now - self._jwks_cache_at) < self._jwks_cache_ttl:
            return self._jwks_cache

        # Serialize refreshes through the lock
        async with self._cache_lock:
            # Double-check after acquiring -- another task may have refreshed
            now = time.monotonic()
            if self._jwks_cache is not None and (now - self._jwks_cache_at) < self._jwks_cache_ttl:
                return self._jwks_cache

            try:
                client = await asyncio.to_thread(jwk_client_cls, self._jwks_url)
                self._jwks_cache = client
                self._jwks_cache_at = time.monotonic()
                logger.info("JWKS refreshed from %s", self._jwks_url)
                return client
            except Exception:
                # JWKS fetch failed -- use stale cache if available
                if self._jwks_cache is not None:
                    logger.warning("JWKS refresh failed, using stale cache")
                    return self._jwks_cache
                raise

    def _extract_roles(self, claims: dict[str, Any]) -> list[str]:
        """Extract roles from claims using the configured role_claim path."""
        value = self._extract_nested(claims, self._role_claim)
        if isinstance(value, list):
            return [str(r) for r in value]
        if isinstance(value, str):
            return [value]
        return []

    @staticmethod
    def _extract_nested(claims: dict[str, Any], path: str) -> Any:
        """Extract a nested value from claims using dot notation.

        Example: "realm_access.roles" → claims["realm_access"]["roles"]

        If the full path exists as a top-level key (e.g., Auth0's
        "https://myapp.com/roles"), it's returned directly before
        attempting dot-notation traversal.
        """
        if not path:
            return None

        # First: try exact match (handles URL-style claim names like Auth0)
        if path in claims:
            return claims[path]

        # Second: dot-notation traversal for nested claims (Keycloak, Entra ID)
        current: Any = claims
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
