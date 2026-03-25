"""SQLModel-based persistence models.

All database tables are defined here as SQLModel classes. These serve triple
duty: database schema (CREATE TABLE), Pydantic validation (request/response),
and Python dataclass (business logic).

Usage:
    from stronghold.models import AgentRecord, get_engine, get_session

Engine setup:
    The async engine is created lazily via get_engine(database_url).
    Alembic manages migrations — do NOT call create_all() in production.
"""

from stronghold.models.agent import AgentRecord
from stronghold.models.engine import get_engine, get_session

__all__ = [
    "AgentRecord",
    "get_engine",
    "get_session",
]
