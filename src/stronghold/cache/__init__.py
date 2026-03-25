"""Redis-backed cache, sessions, and rate limiting.

Provides distributed implementations of the same protocols that InMemory
classes implement for local dev. DI container selects based on config:

    session_backend: redis    # or "memory" or "postgres"
    cache_backend: redis      # or "memory"
    rate_limit_backend: redis  # or "memory"
"""

from stronghold.cache.redis_pool import close_redis, get_redis

__all__ = ["get_redis", "close_redis"]
