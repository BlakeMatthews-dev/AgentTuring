"""Composite authentication provider: tries multiple providers in order.

Used when multiple auth mechanisms coexist:
1. JWT (Keycloak/Entra ID) — for SSO users
2. Static API key + OpenWebUI headers — for service-to-service + dashboard
3. Webhook secret — for n8n/external integrations

First provider to succeed wins. All fail → ValueError.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext

logger = logging.getLogger("stronghold.auth.composite")


class CompositeAuthProvider:
    """Tries multiple auth providers in order. First success wins."""

    def __init__(self, providers: list[Any]) -> None:
        self._providers = providers

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Try each provider. Return first successful AuthContext.

        Raises ValueError if ALL providers fail.
        """
        last_error: Exception | None = None

        for provider in self._providers:
            try:
                result: AuthContext = await provider.authenticate(authorization, headers=headers)
                return result
            except Exception as e:  # noqa: BLE001
                last_error = e
                continue

        # L1: Don't leak internal provider details in error messages.
        # Log the full error for debugging, return generic message to caller.
        if last_error:
            logger.debug("All auth providers failed. Last error: %s", last_error)
        raise ValueError("Authentication failed")
