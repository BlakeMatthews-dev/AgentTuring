"""Async SQLAlchemy engine and session factory.

Uses asyncpg as the driver (already a dependency). The engine is created once
and reused across the application lifetime.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator  # noqa: TC003
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

logger = logging.getLogger("stronghold.models.engine")

_engine: AsyncEngine | None = None


_engine_url: str = ""


def get_engine(database_url: str) -> AsyncEngine:
    """Get or create the async SQLAlchemy engine.

    Converts postgresql:// to postgresql+asyncpg:// if needed.
    Raises if called with a different URL after initialization.
    """
    global _engine, _engine_url  # noqa: PLW0603
    if _engine is not None:
        if database_url and database_url != _engine_url:
            msg = (
                "Engine already initialized with a different URL. "
                "Call close_engine() first to reinitialize."
            )
            raise RuntimeError(msg)
        return _engine

    _engine_url = database_url
    url = database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    _engine = create_async_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        echo=False,
    )
    logger.info("SQLAlchemy async engine created")
    return _engine


@asynccontextmanager
async def get_session(database_url: str = "") -> AsyncGenerator[AsyncSession, None]:
    """Get an async session for database operations.

    Usage:
        async with get_session(url) as session:
            result = await session.exec(select(AgentRecord))
    """
    engine = get_engine(database_url) if database_url else _engine
    if engine is None:
        msg = "Engine not initialized. Call get_engine(database_url) first."
        raise RuntimeError(msg)

    async with AsyncSession(engine) as session:
        yield session


async def close_engine() -> None:
    """Dispose the engine and close all connections."""
    global _engine, _engine_url  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _engine_url = ""
        logger.info("SQLAlchemy engine disposed")
