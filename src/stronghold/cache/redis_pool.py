"""Redis connection pool management.

Single shared pool for sessions, rate limiting, and caching.
Uses redis[hiredis] for C-level parsing performance.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger("stronghold.cache.redis")

_pool: aioredis.Redis | None = None


def _mask_url(url: str) -> str:
    """Mask credentials in a Redis URL for safe logging."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.password or parsed.username:
            host_port = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
            return f"redis://***@{host_port}{parsed.path}"
        return url
    except Exception:
        return "redis://***"


async def get_redis(redis_url: str = "redis://localhost:6379/0") -> aioredis.Redis:
    """Get or create the shared Redis connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = aioredis.from_url(
            redis_url,
            decode_responses=True,
            max_connections=20,
        )
        # Verify connection
        await _pool.ping()  # type: ignore[misc]
        masked = _mask_url(redis_url)
        logger.info("Redis pool created: %s", masked)
    return _pool


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis pool closed")
