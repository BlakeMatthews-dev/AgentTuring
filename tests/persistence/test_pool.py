"""Tests for persistence pool management (asyncpg).

Because there is no real asyncpg server available in unit-test CI and asyncpg
does not support sqlite fallback, we still have to use a fake for
``asyncpg.create_pool``. To keep these tests honest we do two things
differently than a naive ``MagicMock``-based test:

1. The fake exposes a real ``close()`` / ``acquire()`` surface and records
   every call it received — we assert on what the *real* production code did
   to the pool (called ``close``, singleton-cached, never touched on empty
   migrations dir), not on ``mock.call_count``.
2. For ``run_migrations`` we drive the real function against a fake connection
   that records the actual SQL string each call emitted, so the test proves
   the migration code generated the expected DDL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

import stronghold.persistence as persistence


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset global pool state between tests."""
    persistence._pool = None
    yield
    persistence._pool = None


# ── Test doubles that record real interactions ────────────────────────


class FakePool:
    """A hand-rolled stand-in for ``asyncpg.Pool`` that records calls."""

    def __init__(self) -> None:
        self.close_calls = 0
        self.acquire_calls = 0
        self._conn: FakeConnection | None = None

    def set_connection(self, conn: "FakeConnection") -> None:
        self._conn = conn

    async def close(self) -> None:
        self.close_calls += 1

    @asynccontextmanager
    async def acquire(self):
        self.acquire_calls += 1
        assert self._conn is not None, "Test must set_connection() before acquire()"
        yield self._conn


class FakeConnection:
    """Records every execute/fetch/fetchval call — exposes real asyncpg surface."""

    def __init__(
        self,
        *,
        applied_rows: list[dict] | None = None,
        has_tables: bool = False,
    ) -> None:
        self.applied_rows = applied_rows or []
        self.has_tables = has_tables
        self.executed: list[tuple[str, tuple]] = []  # (sql, args)
        self.fetched: list[str] = []
        self.fetchval_calls: list[str] = []

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetch(self, sql: str, *args) -> list[dict]:
        self.fetched.append(sql)
        return list(self.applied_rows)

    async def fetchval(self, sql: str, *args):
        self.fetchval_calls.append(sql)
        return self.has_tables


# ── get_pool ─────────────────────────────────────────────────────────


async def test_get_pool_creates_pool(monkeypatch):
    """First call creates the pool via create_pool, then caches the module-level _pool."""
    captured: dict = {}

    async def fake_create_pool(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakePool()

    monkeypatch.setattr(persistence.asyncpg, "create_pool", fake_create_pool)

    pool = await persistence.get_pool("postgresql://localhost/test")

    # Real behavior: create_pool got our exact arguments.
    assert captured["url"] == "postgresql://localhost/test"
    assert captured["kwargs"] == {"min_size": 2, "max_size": 10, "command_timeout": 30}
    # Real behavior: module-level pool is now the returned pool. Exact
    # type identity — a subclass sneaking in would be a regression.
    assert type(pool) is FakePool
    assert persistence._pool is pool


async def test_get_pool_returns_existing_without_recreating(monkeypatch):
    """Second call returns the cached pool; create_pool is not invoked again."""
    create_count = 0

    async def fake_create_pool(url, **kwargs):
        nonlocal create_count
        create_count += 1
        return FakePool()

    monkeypatch.setattr(persistence.asyncpg, "create_pool", fake_create_pool)

    pool1 = await persistence.get_pool("postgresql://localhost/test")
    pool2 = await persistence.get_pool("postgresql://localhost/test")

    # Behavioral: same instance returned both times (cached singleton).
    assert pool1 is pool2
    # Behavioral: create_pool was awaited exactly once across both calls.
    assert create_count == 1


# ── close_pool ───────────────────────────────────────────────────────


async def test_close_pool():
    """close_pool calls pool.close() exactly once and clears the singleton."""
    fake = FakePool()
    persistence._pool = fake
    await persistence.close_pool()
    # Behavioral: close was invoked on the real pool surface once.
    assert fake.close_calls == 1
    # Behavioral: singleton cleared so next get_pool() would recreate.
    assert persistence._pool is None


async def test_close_pool_when_none():
    """close_pool is a no-op when no pool exists."""
    await persistence.close_pool()
    assert persistence._pool is None


# ── run_migrations ───────────────────────────────────────────────────


async def test_run_migrations_no_dir(tmp_path):
    """Warns and returns without ever acquiring a connection."""
    fake = FakePool()
    # No connection set — if acquire() were called, the assert in FakePool would fire.
    await persistence.run_migrations(fake, str(tmp_path / "nonexistent"))
    # Behavioral: no connection acquired, because the dir did not exist.
    assert fake.acquire_calls == 0


async def test_run_migrations_applies_sql(tmp_path):
    """Applies pending migrations in sorted order, running each file's SQL
    and recording each filename in _migrations."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")
    (mig_dir / "002_add_col.sql").write_text("ALTER TABLE test ADD COLUMN name TEXT;")

    conn = FakeConnection(applied_rows=[], has_tables=False)
    pool = FakePool()
    pool.set_connection(conn)

    await persistence.run_migrations(pool, str(mig_dir))

    # Real behavior: acquired exactly one connection for the whole run.
    assert pool.acquire_calls == 1

    executed_sql = [sql for sql, _args in conn.executed]
    joined = "\n".join(executed_sql)
    # Real behavior: the body of BOTH migration files was executed against the DB.
    assert "CREATE TABLE test (id INT);" in joined
    assert "ALTER TABLE test ADD COLUMN name TEXT;" in joined

    # Real behavior: each filename was recorded in _migrations via INSERT, in sorted order.
    migration_inserts = [
        (sql, args)
        for sql, args in conn.executed
        if "_migrations" in sql and "INSERT" in sql
    ]
    assert len(migration_inserts) == 2
    # The filename is passed as an argument ($1) to a parameterised INSERT.
    assert migration_inserts[0][1] == ("001_init.sql",)
    assert migration_inserts[1][1] == ("002_add_col.sql",)


async def test_run_migrations_skips_applied(tmp_path):
    """Already-applied migrations are skipped."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")

    conn = FakeConnection(applied_rows=[{"name": "001_init.sql"}])
    pool = FakePool()
    pool.set_connection(conn)

    await persistence.run_migrations(pool, str(mig_dir))

    executed_sql = [sql for sql, _args in conn.executed]
    # Real behavior: the migration body was NOT applied a second time.
    for sql in executed_sql:
        assert "CREATE TABLE test" not in sql


async def test_run_migrations_marks_preexisting(tmp_path):
    """When tables exist but _migrations is empty, mark all as applied."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE test (id INT);")

    conn = FakeConnection(applied_rows=[], has_tables=True)
    pool = FakePool()
    pool.set_connection(conn)

    await persistence.run_migrations(pool, str(mig_dir))

    executed_sql = [sql for sql, _args in conn.executed]
    insert_calls = [sql for sql in executed_sql if "_migrations" in sql and "INSERT" in sql]
    assert len(insert_calls) >= 1
    # Real behavior: the migration body itself was NOT re-executed on the live tables.
    for sql in executed_sql:
        assert "CREATE TABLE test (id INT);" not in sql
