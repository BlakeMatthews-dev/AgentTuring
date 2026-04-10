"""In-memory OAuth store for development and testing.

Production deployments should use PgOAuthStore (backed by PostgreSQL).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from stronghold.mcp.oauth.types import AuthorizationCode, OAuthClient, OAuthToken, TokenClaims


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@runtime_checkable
class OAuthStore(Protocol):
    """Protocol for OAuth client/token persistence."""

    async def register_client(self, client: OAuthClient) -> None: ...
    async def get_client(self, client_id: str) -> OAuthClient | None: ...
    async def store_auth_code(self, code: AuthorizationCode) -> None: ...
    async def consume_auth_code(self, code: str) -> AuthorizationCode | None: ...
    async def store_token(self, token: OAuthToken) -> None: ...
    async def validate_token(self, token_value: str) -> TokenClaims | None: ...
    async def revoke_token(self, token_value: str) -> bool: ...


class InMemoryOAuthStore:
    """In-memory OAuth store for development."""

    def __init__(self) -> None:
        self._clients: dict[str, OAuthClient] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._tokens: dict[str, OAuthToken] = {}

    async def register_client(self, client: OAuthClient) -> None:
        self._clients[client.client_id] = client

    async def get_client(self, client_id: str) -> OAuthClient | None:
        return self._clients.get(client_id)

    async def store_auth_code(self, code: AuthorizationCode) -> None:
        self._codes[code.code] = code

    async def consume_auth_code(self, code: str) -> AuthorizationCode | None:
        auth_code = self._codes.get(code)
        if auth_code is None or auth_code.used:
            return None
        if auth_code.expires_at < datetime.now(timezone.utc):
            return None
        auth_code.used = True
        return auth_code

    async def store_token(self, token: OAuthToken) -> None:
        self._tokens[token.token_hash] = token

    async def validate_token(self, token_value: str) -> TokenClaims | None:
        token_hash = _hash_token(token_value)
        token = self._tokens.get(token_hash)
        if token is None or token.revoked:
            return None
        if token.expires_at < datetime.now(timezone.utc):
            return None
        return TokenClaims(
            user_id=token.user_id,
            tenant_id=token.tenant_id,
            client_id=token.client_id,
            scope=token.scope,
            token_type=token.token_type,
        )

    async def revoke_token(self, token_value: str) -> bool:
        token_hash = _hash_token(token_value)
        token = self._tokens.get(token_hash)
        if token is None:
            return False
        token.revoked = True
        return True


def generate_client_credentials() -> tuple[str, str]:
    """Generate a client_id and client_secret pair."""
    client_id = f"mcp_{secrets.token_urlsafe(16)}"
    client_secret = secrets.token_urlsafe(32)
    return client_id, client_secret


def generate_auth_code() -> str:
    return secrets.token_urlsafe(32)


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def issue_access_token(
    client_id: str, user_id: str, tenant_id: str, scope: str,
    ttl_minutes: int = 15,
) -> tuple[str, OAuthToken]:
    """Generate an access token and its storage record."""
    token_value = generate_token()
    token = OAuthToken(
        token_hash=_hash_token(token_value),
        client_id=client_id,
        user_id=user_id,
        tenant_id=tenant_id,
        scope=scope,
        token_type="access",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    return token_value, token


def issue_refresh_token(
    client_id: str, user_id: str, tenant_id: str, scope: str,
    ttl_days: int = 30,
) -> tuple[str, OAuthToken]:
    """Generate a refresh token and its storage record."""
    token_value = generate_token()
    token = OAuthToken(
        token_hash=_hash_token(token_value),
        client_id=client_id,
        user_id=user_id,
        tenant_id=tenant_id,
        scope=scope,
        token_type="refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    return token_value, token
