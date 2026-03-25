"""Auth provider protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates requests and returns an AuthContext."""

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Returns AuthContext on success, raises AuthError on failure."""
        ...
