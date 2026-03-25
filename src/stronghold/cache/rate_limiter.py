"""Redis-backed rate limiter using sliding window.

Implements the same RateLimiter protocol as InMemoryRateLimiter but uses
Redis sorted sets for distributed rate limiting across multiple instances.

Algorithm: sliding window log via ZRANGEBYSCORE + ZADD.
Each request is logged with its timestamp as the score. To check the rate,
we count entries within the current window. O(log N) per operation.
"""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis  # noqa: TC002

logger = logging.getLogger("stronghold.cache.rate_limiter")


class RedisRateLimiter:
    """Distributed rate limiter backed by Redis sorted sets.

    Implements the RateLimiter protocol (check + record).
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        max_requests: int = 60,
        window_seconds: int = 60,
        key_prefix: str = "stronghold:ratelimit:",
    ) -> None:
        self._redis = redis
        self._max = max_requests
        self._window = window_seconds
        self._prefix = key_prefix

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check if a request is allowed for the given key."""
        now = time.time()
        window_start = now - self._window
        rkey = f"{self._prefix}{key}"

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(rkey, 0, window_start)  # Evict expired entries
        pipe.zcard(rkey)  # Count entries in window
        pipe.zrange(rkey, 0, 0, withscores=True)  # Oldest entry for reset calc
        results = await pipe.execute()

        count: int = results[1]
        remaining = max(0, self._max - count)
        allowed = count < self._max

        # Reset = seconds until the oldest entry in the window expires
        oldest_entries = results[2]
        if oldest_entries:
            oldest_score = oldest_entries[0][1]
            reset_at = oldest_score + self._window
            reset_seconds = max(0, int(reset_at - now))
        else:
            reset_seconds = self._window

        headers = {
            "X-RateLimit-Limit": str(self._max),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_seconds),
        }
        return allowed, headers

    async def record(self, key: str) -> None:
        """Record a request against the key's rate limit."""
        now = time.time()
        rkey = f"{self._prefix}{key}"

        # Use unique member to avoid collisions at same timestamp
        import os

        member = f"{now}:{os.urandom(4).hex()}"

        pipe = self._redis.pipeline()
        pipe.zadd(rkey, {member: now})
        pipe.expire(rkey, self._window + 10)  # TTL = window + buffer
        await pipe.execute()
