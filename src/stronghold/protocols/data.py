"""Data store protocol — abstraction over PostgreSQL."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataStore(Protocol):
    """Abstract storage backend."""

    async def execute(
        self,
        query: str,
        *args: Any,
    ) -> list[dict[str, Any]]:
        """Execute a query and return rows as dicts."""
        ...

    async def execute_one(
        self,
        query: str,
        *args: Any,
    ) -> dict[str, Any] | None:
        """Execute a query and return a single row or None."""
        ...

    async def insert(
        self,
        table: str,
        data: dict[str, Any],
    ) -> int:
        """Insert a row and return the ID."""
        ...
