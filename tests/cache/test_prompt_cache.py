"""Tests for RedisPromptCache using fakeredis."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
import redis

from stronghold.cache.prompt_cache import RedisPromptCache


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def cache(redis_client):
    return RedisPromptCache(redis=redis_client, ttl_seconds=300)


async def test_get_miss(cache):
    result = await cache.get("nonexistent")
    assert result is None


async def test_set_and_get(cache):
    await cache.set("prompt:1", {"text": "hello", "version": 2})
    result = await cache.get("prompt:1")
    assert result == {"text": "hello", "version": 2}


async def test_set_with_custom_ttl(cache, redis_client):
    await cache.set("prompt:2", "value", ttl=60)
    ttl = await redis_client.ttl("stronghold:cache:prompt:2")
    assert 0 < ttl <= 60


async def test_delete(cache):
    await cache.set("prompt:3", "to-delete")
    await cache.delete("prompt:3")
    result = await cache.get("prompt:3")
    assert result is None


async def test_invalidate_pattern(cache):
    """invalidate_pattern removes all matching keys."""
    await cache.set("agent.1", "a1")
    await cache.set("agent.2", "a2")
    await cache.set("prompt.1", "p1")
    await cache.invalidate_pattern("agent.*")
    assert await cache.get("agent.1") is None
    assert await cache.get("agent.2") is None
    # Non-matching key is preserved
    assert await cache.get("prompt.1") == "p1"


async def test_set_serializes_non_json_types(cache):
    """Values with non-serializable types use str() fallback."""
    from datetime import datetime

    val = {"ts": datetime(2026, 1, 1, 12, 0, 0)}
    await cache.set("ts-key", val)
    result = await cache.get("ts-key")
    assert "2026" in result["ts"]


async def test_invalidate_pattern_no_matches(cache):
    """invalidate_pattern is a no-op when nothing matches."""
    await cache.set("keep", "value")
    await cache.invalidate_pattern("nomatch.*")
    assert await cache.get("keep") == "value"


# ---- Redis-down resilience (H18) ----


class _DeadRedis:
    """Fake Redis client that raises ConnectionError on every call."""

    async def get(self, *a, **kw):
        raise redis.ConnectionError("Redis is down")

    async def set(self, *a, **kw):
        raise redis.ConnectionError("Redis is down")

    async def delete(self, *a, **kw):
        raise redis.ConnectionError("Redis is down")

    async def scan(self, *a, **kw):
        raise redis.ConnectionError("Redis is down")

    def pipeline(self):
        raise redis.ConnectionError("Redis is down")


@pytest.fixture
def dead_cache():
    return RedisPromptCache(redis=_DeadRedis(), ttl_seconds=300)


async def test_get_returns_none_when_redis_down(dead_cache):
    """Cache get returns None (cache-miss) when Redis is unreachable."""
    result = await dead_cache.get("any-key")
    assert result is None


async def test_set_does_not_raise_when_redis_down(dead_cache):
    """Cache set is a silent no-op when Redis is unreachable."""
    await dead_cache.set("any-key", {"data": "value"})  # should not raise


async def test_delete_does_not_raise_when_redis_down(dead_cache):
    """Cache delete is a silent no-op when Redis is unreachable."""
    await dead_cache.delete("any-key")  # should not raise


async def test_invalidate_pattern_does_not_raise_when_redis_down(dead_cache):
    """Cache invalidate_pattern is a silent no-op when Redis is unreachable."""
    await dead_cache.invalidate_pattern("agent.*")  # should not raise
