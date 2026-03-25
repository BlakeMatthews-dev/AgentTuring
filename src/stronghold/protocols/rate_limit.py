"""Rate limiter protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    """Per-key request rate limiter.

    Keys are typically user_id, org_id, or IP address.
    Implementations: InMemoryRateLimiter (local), Redis-backed (distributed).
    """

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check if a request is allowed for the given key.

        Returns:
            (allowed, headers) where headers contains X-RateLimit-* values:
            - X-RateLimit-Limit: max requests per window
            - X-RateLimit-Remaining: requests left in current window
            - X-RateLimit-Reset: seconds until window resets
        """
        ...

    async def record(self, key: str) -> None:
        """Record a request against the key's rate limit."""
        ...
