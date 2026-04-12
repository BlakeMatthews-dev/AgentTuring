"""Tests for SQLAlchemy async engine lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import stronghold.models.engine as engine_mod


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset global engine state between tests."""
    engine_mod._engine = None
    engine_mod._engine_url = ""
    yield
    engine_mod._engine = None
    engine_mod._engine_url = ""


# ---- get_engine ----

def test_get_engine_creates_engine():
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        result = engine_mod.get_engine("postgresql://localhost/test")
        assert result is mock_engine
        # Should convert to asyncpg URL
        call_args = mock_create.call_args
        assert "postgresql+asyncpg://" in call_args[0][0]


def test_get_engine_converts_postgres_prefix():
    """postgres:// is also converted to postgresql+asyncpg://."""
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_create.return_value = MagicMock()
        engine_mod.get_engine("postgres://localhost/test")
        call_url = mock_create.call_args[0][0]
        assert call_url.startswith("postgresql+asyncpg://")


def test_get_engine_returns_cached():
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        e1 = engine_mod.get_engine("postgresql://localhost/test")
        e2 = engine_mod.get_engine("postgresql://localhost/test")
        assert e1 is e2
        assert mock_create.call_count == 1


def test_get_engine_raises_on_different_url():
    """Cannot reinitialize with a different URL without closing first."""
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_create.return_value = MagicMock()
        engine_mod.get_engine("postgresql://localhost/db1")
        with pytest.raises(RuntimeError, match="different URL"):
            engine_mod.get_engine("postgresql://localhost/db2")


def test_get_engine_same_url_empty_string():
    """Calling with empty string after init returns cached engine."""
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        engine_mod.get_engine("postgresql://localhost/test")
        result = engine_mod.get_engine("")
        assert result is mock_engine


# ---- get_session ----

async def test_get_session_raises_without_engine():
    """get_session raises if engine was never initialized."""
    with pytest.raises(RuntimeError, match="not initialized"):
        async with engine_mod.get_session():
            pass


async def test_get_session_with_url():
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine
        with patch("stronghold.models.engine.AsyncSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            async with engine_mod.get_session("postgresql://localhost/test") as session:
                assert session is mock_session


# ---- close_engine ----

async def test_close_engine():
    with patch("stronghold.models.engine.create_async_engine") as mock_create:
        mock_engine = AsyncMock()
        mock_create.return_value = mock_engine
        engine_mod.get_engine("postgresql://localhost/test")
        await engine_mod.close_engine()
        mock_engine.dispose.assert_called_once()
        assert engine_mod._engine is None
        assert engine_mod._engine_url == ""


async def test_close_engine_when_none():
    """close_engine is a no-op when no engine exists."""
    await engine_mod.close_engine()
    assert engine_mod._engine is None
