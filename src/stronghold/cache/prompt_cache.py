"""Redis-backed prompt/agent cache.

Caches frequently-accessed prompts and agent configs to avoid hitting
PostgreSQL on every request. Write-through: writes go to DB first,
then cache is updated. TTL ensures eventual consistency.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis  # noqa: TC002

logger = logging.getLogger("stronghold.cache.prompt_cache")


class RedisPromptCache:
    """Cache layer for prompts and agent configurations.

    Sits in front of PgPromptManager / PgAgentRegistry. Callers check
    cache first, fall through to DB on miss, and populate cache on read.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        ttl_seconds: int = 300,
        key_prefix: str = "stronghold:cache:",
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    async def get(self, key: str) -> Any | None:
        """Get a cached value. Returns None on miss."""
        raw = await self._redis.get(f"{self._prefix}{key}")
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a cached value with TTL."""
        await self._redis.set(
            f"{self._prefix}{key}",
            json.dumps(value, default=str),
            ex=ttl or self._ttl,
        )

    async def delete(self, key: str) -> None:
        """Invalidate a cached value."""
        await self._redis.delete(f"{self._prefix}{key}")

    async def invalidate_pattern(self, pattern: str) -> None:
        """Invalidate all keys matching a pattern (e.g., 'agent.*')."""
        full_pattern = f"{self._prefix}{pattern}"
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=full_pattern, count=100)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break
