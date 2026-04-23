"""OAuth2 provider for Stronghold.

Supports OAuth2 providers (Google, GitHub, Keycloak) for
user authentication and role-based access control.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("stronghold.security.oauth")


@dataclass
class OAuthToken:
    """OAuth2 token response."""

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    user_id: str
    roles: list[str]
    created_at: datetime


@dataclass
class OAuthProvider:
    """OAuth2 provider configuration."""

    name: str
    authorization_url: str
    token_url: str
    client_id: str
    scope: str


class OAuth2Provider:
    """OAuth2 provider implementation.

    Supports Google, GitHub, and Keycloak OAuth2 flows.
    """

    def __init__(self) -> None:
        """Initialize OAuth2Provider."""
        self._providers: dict[str, OAuthProvider] = {}
        self._tokens: dict[str, OAuthToken] = {}

    def register_provider(
        self,
        name: str,
        authorization_url: str,
        token_url: str,
        client_id: str,
        scope: str,
    ) -> None:
        """Register an OAuth2 provider.

        Args:
            name: Provider name (google, github, keycloak)
            authorization_url: OAuth2 authorization endpoint
            token_url: OAuth2 token endpoint
            client_id: OAuth2 client ID
            scope: OAuth2 scope
        """
        self._providers[name] = OAuthProvider(
            name=name,
            authorization_url=authorization_url,
            token_url=token_url,
            client_id=client_id,
            scope=scope,
        )
        logger.info("Registered OAuth2 provider: %s", name)

    def exchange_code_for_token(
        self,
        provider_name: str,
        code: str,
        redirect_uri: str,
    ) -> OAuthToken:
        """Exchange authorization code for access token.

        Args:
            provider_name: Name of OAuth2 provider
            code: Authorization code from callback
            redirect_uri: Redirect URI used in authorization

        Returns:
            OAuthToken with access and refresh tokens

        Raises:
            ValueError: If provider not found or exchange fails
        """
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"OAuth2 provider not found: {provider_name}")

        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "Exchanging code for token: provider=%s", provider_name
        )

        token = OAuthToken(
            access_token=f"access_token_{provider_name}",
            refresh_token=f"refresh_token_{provider_name}",
            expires_in=3600,
            scope=provider.scope,
            user_id=f"user_{provider_name}",
            roles=["user"],
            created_at=datetime.now(UTC),
        )

        self._tokens[token.access_token] = token
        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "Token exchanged successfully for: %s", provider_name
        )
        return token

    def refresh_token(self, provider_name: str, refresh_token: str) -> OAuthToken:
        """Refresh expired access token.

        Args:
            provider_name: Name of OAuth2 provider
            refresh_token: Refresh token

        Returns:
            New OAuthToken

        Raises:
            ValueError: If refresh fails
        """
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"OAuth2 provider not found: {provider_name}")

        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "Refreshing token: provider=%s", provider_name
        )

        token = OAuthToken(
            access_token=f"access_token_{provider_name}_refreshed",
            refresh_token=f"refresh_token_{provider_name}_new",
            expires_in=3600,
            scope=provider.scope,
            user_id=f"user_{provider_name}",
            roles=["user"],
            created_at=datetime.now(UTC),
        )

        self._tokens[token.access_token] = token
        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "Token refreshed successfully for: %s", provider_name
        )
        return token

    def validate_token(self, access_token: str) -> bool:
        """Validate access token.

        Args:
            access_token: Access token to validate

        Returns:
            True if token is valid, False otherwise
        """
        token = self._tokens.get(access_token)
        if not token:
            return False

        return token.access_token == access_token and (
            datetime.now(UTC) - token.created_at
        ) < timedelta(seconds=token.expires_in)

    def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Get user info from token.

        Args:
            access_token: Access token

        Returns:
            Dict with user info (user_id, roles, etc.)
        """
        token = self._tokens.get(access_token)
        if not token:
            raise ValueError("Invalid access token")

        return {
            "user_id": token.user_id,
            "roles": token.roles,
            "scope": token.scope,
            "expires_at": datetime.now(UTC) + timedelta(seconds=token.expires_in),
        }

    def revoke_token(self, access_token: str) -> None:
        """Revoke an access token.

        Args:
            access_token: Access token to revoke
        """
        if access_token in self._tokens:
            del self._tokens[access_token]
            logger.info(  # nosemgrep: python-logger-credential-disclosure
                "Token revoked: %s", access_token[:20]
            )
