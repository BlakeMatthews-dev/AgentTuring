"""CanaryStore protocol: per-session token lifecycle management.

Implementations must guarantee:
- Tenant isolation: (session_id, org_id) is the compound key; same session_id
  across different org_ids never shares a token.
- Thread/coroutine safety: concurrent get_or_mint calls for the same key must
  return the same token (no race-minted duplicates).
- rotate() always returns a fresh token distinct from the previous value.
"""

from __future__ import annotations

from typing import Protocol


class CanaryStore(Protocol):
    """Per-session canary token store.

    Tokens are 22-char URL-safe base64 strings (128 bits of entropy).
    get_or_mint is idempotent within a session; rotate replaces the token.
    """

    async def get_or_mint(self, session_id: str, org_id: str) -> str:
        """Return existing token for (session_id, org_id) or mint a fresh one."""
        ...

    async def rotate(self, session_id: str, org_id: str) -> str:
        """Invalidate current token and mint a new one. Returns the new token."""
        ...

    async def revoke(self, session_id: str, org_id: str) -> None:
        """Remove the token for (session_id, org_id) — called at session end."""
        ...
