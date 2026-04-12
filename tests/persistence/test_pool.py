"""Tests for persistence pool management (asyncpg)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import stronghold.persistence as persistence


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset global pool state between tests."""
    persistence._pool = None
    yield
    persistence._pool = None


# ---- get_pool ----

async def test_get_pool_creates_pool():
    mock_pool = AsyncMock()
    with patch("stronghold.persistence.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create:
        pool = await persistence.get_pool("postgresql://localhost/test")
        mock_create.assert_called_once_with(
            "postgresql://localhost/test",
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        assert pool is mock_pool


async def test_get_pool_returns_existing():
    """Second call returns the cached pool without creating a new one."""
    mock_pool = AsyncMock()
    with patch("stronghold.persistence.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create:
        pool1 = await persistence.get_pool("postgresql://localhost/test")
        pool2 = await persistence.get_pool("postgresql://localhost/test")
        assert pool1 is pool2
        assert mock_create.call_count == 1


# ---- close_pool ----

async def test_close_pool():
    mock_pool = AsyncMock()
    persistence._pool = mock_pool
    await persistence.close_pool()
    mock_pool.close.assert_called_once()
    assert persistence._pool is None


async def test_close_pool_when_none():
    """close_pool is a no-op when no pool exists."""
    await persistence.close_pool()
    assert persistence._pool is None


# ---- Helper to build a mock pool with async context manager acquire ----

def _make_mock_pool(mock_conn):
    """Build a mock pool whose acquire() returns an async CM yielding mock_conn."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


# ---- run_migrations ----

async def test_run_migrations_no_dir(tmp_path):
    """Warns and returns when migrations directory doesn't exist."""
    mock_pool = MagicMock()
    await persistence.run_migrations(mock_pool, str(tmp_path / "nonexistent"))
    # acquire should never be called
    mock_pool.acquire.assert_not_called()


async def test_run_migrations_applies_sql(tmp_path):
    """Applies pending migrations in sorted order."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")
    (mig_dir / "002_add_col.sql").write_text("ALTER TABLE test ADD COLUMN name TEXT;")

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])  # no applied migrations
    mock_conn.fetchval = AsyncMock(return_value=False)  # no pre-existing tables

    mock_pool = _make_mock_pool(mock_conn)

    await persistence.run_migrations(mock_pool, str(mig_dir))

    # Should have: CREATE _migrations table, SELECT applied, fetchval for tables,
    # then for each migration: apply SQL + INSERT into _migrations
    assert mock_conn.execute.call_count >= 5


async def test_run_migrations_skips_applied(tmp_path):
    """Already-applied migrations are skipped."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")

    mock_conn = AsyncMock()
    mock_record = {"name": "001_init.sql"}
    mock_conn.fetch = AsyncMock(return_value=[mock_record])

    mock_pool = _make_mock_pool(mock_conn)

    await persistence.run_migrations(mock_pool, str(mig_dir))

    # Should NOT have applied the migration SQL itself
    execute_sql_calls = [str(c) for c in mock_conn.execute.call_args_list]
    for call_str in execute_sql_calls:
        assert "CREATE TABLE test" not in call_str


async def test_run_migrations_marks_preexisting(tmp_path):
    """When tables exist but _migrations is empty, marks all as applied."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])  # empty _migrations
    mock_conn.fetchval = AsyncMock(return_value=True)  # tables exist

    mock_pool = _make_mock_pool(mock_conn)

    await persistence.run_migrations(mock_pool, str(mig_dir))

    # Should INSERT into _migrations to mark as applied, not execute the migration SQL
    execute_calls = [str(c) for c in mock_conn.execute.call_args_list]
    insert_calls = [c for c in execute_calls if "_migrations" in c and "INSERT" in c]
    assert len(insert_calls) >= 1
