"""Tests for RedisRateLimiter using fakeredis."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from stronghold.cache.rate_limiter import RedisRateLimiter


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def limiter(redis_client):
    return RedisRateLimiter(redis=redis_client, max_requests=5, window_seconds=60)


async def test_check_allows_under_limit(limiter):
    allowed, headers = await limiter.check("user:1")
    assert allowed is True
    assert headers["X-RateLimit-Limit"] == "5"
    assert headers["X-RateLimit-Remaining"] == "5"


async def test_check_after_records(limiter):
    """After recording requests, remaining count decreases."""
    await limiter.record("user:2")
    await limiter.record("user:2")
    allowed, headers = await limiter.check("user:2")
    assert allowed is True
    assert headers["X-RateLimit-Remaining"] == "3"


async def test_check_blocks_at_limit(limiter):
    """After max_requests, further checks return not allowed."""
    for _ in range(5):
        await limiter.record("user:3")
    allowed, headers = await limiter.check("user:3")
    assert allowed is False
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_record_sets_expiry(limiter, redis_client):
    """Recording a request sets a TTL on the key."""
    await limiter.record("user:4")
    ttl = await redis_client.ttl("stronghold:ratelimit:user:4")
    assert ttl > 0
    assert ttl <= 70  # window_seconds + 10 buffer


async def test_separate_keys_independent(limiter):
    """Different keys have independent rate limits."""
    for _ in range(5):
        await limiter.record("user:5")
    allowed_5, _ = await limiter.check("user:5")
    allowed_6, _ = await limiter.check("user:6")
    assert allowed_5 is False
    assert allowed_6 is True


async def test_headers_have_reset(limiter):
    """Headers include a reset time."""
    await limiter.record("user:7")
    _, headers = await limiter.check("user:7")
    reset = int(headers["X-RateLimit-Reset"])
    assert 0 <= reset <= 60


async def test_check_no_entries_reset_is_window(limiter):
    """When no entries exist, reset equals window_seconds."""
    _, headers = await limiter.check("user:8")
    assert headers["X-RateLimit-Reset"] == "60"
