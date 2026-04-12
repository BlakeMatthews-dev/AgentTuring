"""Per-user credential vault protocol (ADR-K8S-018).

VaultClient manages per-user secrets in a path-based store (OpenBao/Vault).
Path convention: ``users/{org_id}/{user_id}/{service}/{key}``

Unlike SecretBackend (which resolves config-time references), VaultClient
is the runtime interface for tool executors that need per-user credentials
to act on behalf of individual users (GitHub PATs, JIRA tokens, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class VaultSecret:
    """A secret value with metadata."""

    value: str
    service: str
    key: str
    version: int | None = None


@runtime_checkable
class VaultClient(Protocol):
    """Per-user credential vault for tool executors."""

    async def get_user_secret(
        self,
        org_id: str,
        user_id: str,
        service: str,
        key: str,
    ) -> VaultSecret:
        """Read a per-user secret.

        Raises:
            LookupError: Secret does not exist at this path.
            PermissionError: Caller not authorized for this user/org path.
        """
        ...

    async def put_user_secret(
        self,
        org_id: str,
        user_id: str,
        service: str,
        key: str,
        value: str,
    ) -> VaultSecret:
        """Write or update a per-user secret.

        Returns the written secret with updated version.

        Raises:
            PermissionError: Caller not authorized.
        """
        ...

    async def delete_user_secret(
        self,
        org_id: str,
        user_id: str,
        service: str,
        key: str,
    ) -> None:
        """Delete a per-user secret.

        Idempotent — deleting a non-existent secret is not an error.

        Raises:
            PermissionError: Caller not authorized.
        """
        ...

    async def list_user_services(
        self,
        org_id: str,
        user_id: str,
    ) -> list[str]:
        """List services that have stored secrets for this user.

        Returns an empty list if the user has no secrets.
        """
        ...

    async def revoke_user(
        self,
        org_id: str,
        user_id: str,
    ) -> int:
        """Revoke all secrets for a user (e.g., on offboarding).

        Returns the count of secrets deleted.
        """
        ...

    async def close(self) -> None:
        """Release connections. Idempotent."""
        ...
