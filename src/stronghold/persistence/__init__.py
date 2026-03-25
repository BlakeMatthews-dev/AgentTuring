"""PostgreSQL persistence layer."""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger("stronghold.persistence")

_pool: asyncpg.Pool | None = None


async def get_pool(database_url: str) -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("PostgreSQL pool created: %s", database_url.split("@")[-1])
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


async def run_migrations(pool: asyncpg.Pool, migrations_dir: str = "") -> None:
    """Run pending SQL migrations."""
    from pathlib import Path

    if not migrations_dir:
        # Try multiple paths: installed package (/app), development (relative)
        candidates = [
            Path("/app/migrations"),
            Path(__file__).parent.parent.parent.parent / "migrations",
            Path("migrations"),
        ]
        for candidate in candidates:
            if candidate.exists():
                migrations_dir = str(candidate)
                break
        else:
            migrations_dir = str(candidates[0])  # Will warn below

    mig_path = Path(migrations_dir)
    if not mig_path.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        applied: set[str] = {r["name"] for r in await conn.fetch("SELECT name FROM _migrations")}

        # If tables exist but _migrations is empty, mark init scripts as applied
        if not applied:
            has_tables = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='agents')"
            )
            if has_tables:
                for sql_file in sorted(mig_path.glob("*.sql")):
                    await conn.execute("INSERT INTO _migrations (name) VALUES ($1)", sql_file.name)
                    logger.info("Marked pre-existing migration: %s", sql_file.name)
                return

        for sql_file in sorted(mig_path.glob("*.sql")):
            if sql_file.name not in applied:
                logger.info("Applying migration: %s", sql_file.name)
                sql = sql_file.read_text()
                await conn.execute(sql)
                await conn.execute("INSERT INTO _migrations (name) VALUES ($1)", sql_file.name)
                logger.info("Migration applied: %s", sql_file.name)
