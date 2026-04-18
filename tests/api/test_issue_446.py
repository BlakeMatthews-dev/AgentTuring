"""Tests for stronghold.cache.redis_pool (originally issue #446: F541).

The original file had a trivial "module loads" test that only checked
``hasattr(mod, "get_redis")`` etc. — the type annotations and imports
already guarantee those names exist. That was replaced with behavioural
tests for ``_mask_url`` (the credential-scrubbing helper) and the
real pool lifecycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import stronghold.cache.redis_pool as redis_pool_mod
from stronghold.cache.redis_pool import _mask_url, close_redis, get_redis


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset the module-level singleton before/after each test."""
    redis_pool_mod._pool = None
    yield
    redis_pool_mod._pool = None


class TestGetRedisAndCloseRedis:
    """Lifecycle tests for the singleton connection pool."""

    @patch("stronghold.cache.redis_pool.aioredis.from_url")
    async def test_get_redis_creates_pool_and_pings(
        self, mock_from_url: AsyncMock
    ) -> None:
        """First call builds the pool and verifies connectivity via PING."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_from_url.return_value = mock_redis

        result = await get_redis("redis://localhost:6379/0")

        assert result is mock_redis
        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            decode_responses=True,
            max_connections=20,
        )
        mock_redis.ping.assert_awaited_once()

    @patch("stronghold.cache.redis_pool.aioredis.from_url")
    async def test_get_redis_reuses_existing_pool(
        self, mock_from_url: AsyncMock
    ) -> None:
        """Second call returns the cached pool without rebuilding."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_from_url.return_value = mock_redis

        first = await get_redis()
        second = await get_redis()

        # Identity check is the real invariant — same pool object returned,
        # proving the singleton was reused rather than rebuilt.
        assert first is second

    @patch("stronghold.cache.redis_pool.aioredis.from_url")
    async def test_close_redis_calls_aclose_and_clears_singleton(
        self, mock_from_url: AsyncMock
    ) -> None:
        """close_redis closes the client and resets the module state
        so the next ``get_redis`` rebuilds. Earlier versions of this
        test stubbed out close_redis itself, so the assertion could
        never fire — this version drives the real function.
        """
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_from_url.return_value = mock_redis

        await get_redis()
        assert redis_pool_mod._pool is mock_redis

        await close_redis()
        mock_redis.aclose.assert_awaited_once()
        assert redis_pool_mod._pool is None

    async def test_close_redis_no_op_when_never_opened(self) -> None:
        """Calling close_redis before get_redis is safe (idempotent)."""
        # No raise — pool was never opened, close is a no-op.
        await close_redis()

        assert redis_pool_mod._pool is None


class TestMaskUrl:
    """The _mask_url helper must scrub credentials before they're logged."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Plain URLs are left alone.
            ("redis://localhost:6379/0", "redis://localhost:6379/0"),
            ("redis://redis.internal:6380/3", "redis://redis.internal:6380/3"),
            # Password present — scrub userinfo.
            (
                "redis://:hunter2@localhost:6379/0",
                "redis://***@localhost:6379/0",
            ),
            # Username + password — scrub both.
            (
                "redis://user:pass@redis.example.com:6379/0",
                "redis://***@redis.example.com:6379/0",
            ),
            # No port — still masks correctly and preserves host.
            (
                "redis://user:pw@redis.example.com/0",
                "redis://***@redis.example.com/0",
            ),
        ],
    )
    def test_masks_credentials_but_preserves_host_and_db(
        self, raw: str, expected: str
    ) -> None:
        assert _mask_url(raw) == expected

    def test_garbage_input_falls_back_to_fully_masked(self) -> None:
        """If the URL can't be parsed, the helper must not leak the raw
        string into logs — it returns the opaque ``redis://***``."""
        # Force urlparse to raise by feeding it a non-string.
        assert _mask_url(42) == "redis://***"  # type: ignore[arg-type]
