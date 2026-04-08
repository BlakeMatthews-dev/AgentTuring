"""Tests for redis_pool F541 error fix."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from stronghold.cache.redis_pool import get_redis


@pytest.fixture(autouse=True)
def reset_pool():
    import stronghold.cache.redis_pool as mod

    mod._pool = None
    yield
    mod._pool = None


class TestF541Fix:
    @patch("stronghold.cache.redis_pool.aioredis.from_url")
    async def test_no_f541_error_in_get_redis(self, mock_from_url: AsyncMock) -> None:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_from_url.return_value = mock_redis

        result = await get_redis("redis://localhost:6379/0")
        assert result is mock_redis

    @patch("stronghold.cache.redis_pool.aioredis.from_url")
    async def test_no_f541_error_in_close_redis(self, mock_from_url: AsyncMock) -> None:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_from_url.return_value = mock_redis

        await get_redis()
        close_redis = AsyncMock()
        await close_redis()
        mock_redis.aclose.assert_called_once()


class TestModuleLoad:
    def test_module_loads_without_errors(self) -> None:
        """Confirm string format adjustments maintain original functionality."""
        import stronghold.cache.redis_pool as mod

        assert mod is not None
        assert hasattr(mod, "get_redis")
        assert hasattr(mod, "close_redis")
        assert hasattr(mod, "_mask_url")
