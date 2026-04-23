"""InMemoryCanaryStore: in-memory implementation of CanaryStore.

Production deployments should use Redis (TTL-backed, atomic get-or-set).
This implementation is for testing and single-process deployments.

Tenant isolation: the store key is (session_id, org_id). Identical session_ids
across different org_ids never share a token — the composite key prevents it.
"""

from __future__ import annotations

import asyncio

from stronghold.security.warden.canary import generate_canary


class InMemoryCanaryStore:
    """Thread-safe in-memory canary token store.

    Suitable for testing and single-process deployments.
    The asyncio.Lock ensures concurrent coroutines don't race on get_or_mint.
    """

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def get_or_mint(self, session_id: str, org_id: str) -> str:
        """Return existing token or mint a new one. Idempotent within session."""
        key = (session_id, org_id)
        async with self._lock:
            if key not in self._tokens:
                self._tokens[key] = generate_canary()
            return self._tokens[key]

    async def rotate(self, session_id: str, org_id: str) -> str:
        """Replace the current token with a fresh one. Returns the new token."""
        key = (session_id, org_id)
        async with self._lock:
            new_token = generate_canary()
            self._tokens[key] = new_token
            return new_token

    async def revoke(self, session_id: str, org_id: str) -> None:
        """Remove the token for (session_id, org_id)."""
        key = (session_id, org_id)
        async with self._lock:
            self._tokens.pop(key, None)
