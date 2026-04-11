"""OAuth 2.1 data types for MCP authentication (ADR-K8S-024)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class OAuthClient:
    """A dynamically registered OAuth client."""

    client_id: str
    client_secret_hash: str  # argon2 or bcrypt hash, never plaintext
    client_name: str = ""
    redirect_uris: list[str] = field(default_factory=list)
    grant_types: list[str] = field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "client_secret_post"
    scope: str = "tools prompts resources"
    tenant_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AuthorizationCode:
    """A one-time authorization code issued during the consent flow."""

    code: str
    client_id: str
    user_id: str
    tenant_id: str
    redirect_uri: str
    scope: str
    code_challenge: str  # S256 PKCE challenge
    code_challenge_method: str = "S256"
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used: bool = False


@dataclass
class OAuthToken:
    """An issued access or refresh token."""

    token_hash: str  # SHA-256 hash of the token value
    client_id: str
    user_id: str
    tenant_id: str
    scope: str
    token_type: str = "access"  # "access" or "refresh"
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked: bool = False


@dataclass
class TokenClaims:
    """Extracted claims from a validated token — the identity context."""

    user_id: str
    tenant_id: str
    client_id: str
    scope: str
    token_type: str = "access"
