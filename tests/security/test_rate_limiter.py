"""Rate limiter tests: sliding window, burst, key isolation."""

from __future__ import annotations

import pytest

from stronghold.security.rate_limiter import InMemoryRateLimiter
from stronghold.types.config import RateLimitConfig


class TestInMemoryRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_under_limit(self) -> None:
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=5))
        for _ in range(5):
            allowed, headers = await limiter.check("user:alice")
            assert allowed
            await limiter.record("user:alice")

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self) -> None:
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=3))
        for _ in range(3):
            await limiter.record("user:alice")

        allowed, headers = await limiter.check("user:alice")
        assert not allowed
        assert headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_different_keys_independent(self) -> None:
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=2))
        await limiter.record("user:alice")
        await limiter.record("user:alice")

        # Alice is blocked
        allowed_a, _ = await limiter.check("user:alice")
        assert not allowed_a

        # Bob is fine
        allowed_b, _ = await limiter.check("user:bob")
        assert allowed_b

    @pytest.mark.asyncio
    async def test_disabled_always_allows(self) -> None:
        limiter = InMemoryRateLimiter(RateLimitConfig(enabled=False))
        for _ in range(100):
            allowed, _ = await limiter.check("user:flood")
            assert allowed

    @pytest.mark.asyncio
    async def test_headers_present(self) -> None:
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=10))
        _, headers = await limiter.check("user:alice")
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers
        assert headers["X-RateLimit-Limit"] == "10"
