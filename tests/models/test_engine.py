"""Tests for SQLAlchemy async engine lifecycle.

Uses real SQLAlchemy ``AsyncEngine`` instances (no mocked ``create_async_engine``)
so these tests actually exercise the production URL rewriting, engine caching,
and ``dispose()`` behavior.

SQLAlchemy engine creation is lazy — no network connection is made until the
engine is first used — so constructing an engine for a
``postgresql+asyncpg://localhost`` URL in a unit-test environment is safe,
and ``AsyncEngine.dispose()`` on a never-connected pool is also safe.

For the ``get_session`` round-trip we use a real in-memory ``sqlite+aiosqlite``
engine, which lets us run an actual ``SELECT 1`` through a real
``AsyncSession``. Sqlite's ``StaticPool`` does not accept the production
``pool_size`` / ``max_overflow`` / ``pool_timeout`` kwargs, so we wrap
``create_async_engine`` with a tiny kwarg-stripper — only for sqlite URLs —
in the two tests that exercise a live session.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine as _real_create_engine

import stronghold.models.engine as engine_mod


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset global engine state between tests."""
    engine_mod._engine = None
    engine_mod._engine_url = ""
    yield
    engine_mod._engine = None
    engine_mod._engine_url = ""


def _sqlite_tolerant_create(url, **kwargs):
    """Wrap create_async_engine so sqlite URLs drop pg-pool kwargs."""
    if "sqlite" in str(url):
        for k in ("pool_size", "max_overflow", "pool_timeout"):
            kwargs.pop(k, None)
    return _real_create_engine(url, **kwargs)


# ── get_engine ────────────────────────────────────────────────────────


def test_get_engine_creates_engine():
    """get_engine returns a real AsyncEngine whose URL was rewritten to asyncpg."""
    result = engine_mod.get_engine("postgresql://localhost/test")

    # Exact-type identity. ``result.url`` below also only exists on AsyncEngine.
    assert type(result) is AsyncEngine
    # Real behavior: the postgresql:// prefix was rewritten to asyncpg.
    assert str(result.url).startswith("postgresql+asyncpg://")
    assert result.url.host == "localhost"
    assert result.url.database == "test"


def test_get_engine_converts_postgres_prefix():
    """postgres:// is also converted to postgresql+asyncpg://."""
    result = engine_mod.get_engine("postgres://localhost/test")
    assert type(result) is AsyncEngine
    assert str(result.url).startswith("postgresql+asyncpg://")


def test_get_engine_caches_across_calls():
    """Repeated calls with the same URL return the *same* engine instance.

    The production code returns the cached singleton, so identity (``is``)
    is the right check — no new engine object is produced on cache hits.
    """
    e1 = engine_mod.get_engine("postgresql://localhost/test")
    e2 = engine_mod.get_engine("postgresql://localhost/test")
    e3 = engine_mod.get_engine("postgresql://localhost/test")

    assert e1 is e2 is e3
    assert type(e1) is AsyncEngine
    # Real behavior: cached URL persisted after the first call.
    assert engine_mod._engine_url == "postgresql://localhost/test"


def test_get_engine_raises_on_different_url():
    """Cannot reinitialize with a different URL without closing first."""
    engine_mod.get_engine("postgresql://localhost/db1")
    with pytest.raises(RuntimeError, match="different URL"):
        engine_mod.get_engine("postgresql://localhost/db2")


def test_get_engine_same_url_empty_string():
    """Calling with empty string after init returns cached engine."""
    first = engine_mod.get_engine("postgresql://localhost/test")
    cached = engine_mod.get_engine("")
    assert cached is first


# ── get_session ───────────────────────────────────────────────────────


async def test_get_session_raises_without_engine():
    """get_session raises if engine was never initialized."""
    with pytest.raises(RuntimeError, match="not initialized"):
        async with engine_mod.get_session():
            pass


async def test_get_session_with_url(monkeypatch):
    """get_session opens a real AsyncSession and can execute a query.

    Uses an in-memory sqlite+aiosqlite engine so we drive the real
    AsyncSession through the real production get_session() path.
    """
    monkeypatch.setattr(engine_mod, "create_async_engine", _sqlite_tolerant_create)

    async with engine_mod.get_session("sqlite+aiosqlite:///:memory:") as session:
        # Real behavior: the yielded object is a real AsyncSession that can
        # execute SQL on a real (sqlite) engine.
        result = await session.execute(text("SELECT 1 AS one"))
        row = result.one()
        assert row.one == 1


# ── close_engine ──────────────────────────────────────────────────────


async def test_close_engine():
    """close_engine disposes the real engine and resets the singleton.

    Instead of asserting on mock internals, we observe two real behaviors:
    1. After close, the engine's pool is disposed (it accepts no new
       connections — ``pool.status()`` reports size 0).
    2. The module-level singleton is cleared so a subsequent ``get_engine``
       call would build a new engine.
    """
    engine_mod.get_engine("postgresql://localhost/test")
    real_engine = engine_mod._engine
    assert real_engine is not None

    # Capture the underlying sync pool identity before close — dispose()
    # replaces the pool with a fresh one as part of tearing the engine down.
    pool_before = real_engine.sync_engine.pool

    await engine_mod.close_engine()

    # Real behavior: module-level state is cleared.
    assert engine_mod._engine is None
    assert engine_mod._engine_url == ""

    # Real behavior: dispose() actually ran on the real engine — SQLAlchemy
    # swaps the pool instance as part of disposal, so identity differs.
    assert real_engine.sync_engine.pool is not pool_before


async def test_close_engine_when_none():
    """close_engine is a no-op when no engine exists."""
    await engine_mod.close_engine()
    assert engine_mod._engine is None
