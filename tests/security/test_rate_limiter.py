"""Rate limiter tests: sliding window, burst, key isolation, concurrency."""

from __future__ import annotations

import asyncio

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


class TestRateLimiterConcurrency:
    """H10: Concurrent check-and-record must not allow bypass."""

    @pytest.mark.asyncio
    async def test_has_lock_attribute(self) -> None:
        """Limiter must hold an asyncio.Lock for serializing state access."""
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=5))
        assert hasattr(limiter, "_lock"), "InMemoryRateLimiter must have a _lock attribute"
        assert isinstance(limiter._lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_check_and_record_atomic(self) -> None:
        """check_and_record must atomically check + record in one call."""
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=3, burst_limit=0))
        results = await asyncio.gather(
            *(limiter.check_and_record("user:atomic") for _ in range(10))
        )
        allowed_count = sum(1 for allowed, _ in results if allowed)
        assert allowed_count == 3, f"Expected exactly 3 allowed, got {allowed_count}"

    @pytest.mark.asyncio
    async def test_check_and_record_respects_limit_under_concurrency(self) -> None:
        """Concurrent check_and_record calls must never exceed the RPM."""
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=5, burst_limit=0))
        results = await asyncio.gather(*(limiter.check_and_record("user:race") for _ in range(50)))
        allowed_count = sum(1 for allowed, _ in results if allowed)
        assert allowed_count <= 5, (
            f"Concurrent bypass: {allowed_count} requests allowed, limit is 5"
        )

    @pytest.mark.asyncio
    async def test_check_still_works_standalone(self) -> None:
        """Existing check() + record() API still works correctly."""
        limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=2, burst_limit=0))
        ok1, _ = await limiter.check("user:x")
        assert ok1
        await limiter.record("user:x")
        ok2, _ = await limiter.check("user:x")
        assert ok2
        await limiter.record("user:x")
        ok3, _ = await limiter.check("user:x")
        assert not ok3
