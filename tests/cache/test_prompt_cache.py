"""Tests for RedisPromptCache using fakeredis."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

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
