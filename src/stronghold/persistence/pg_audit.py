"""PostgreSQL audit log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.types.security import AuditEntry

if TYPE_CHECKING:
    import asyncpg


_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset(
    {
        "org_id",
        "user_id",
        "agent_id",
    }
)


class PgAuditLog:
    """PostgreSQL-backed immutable audit log."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (boundary, user_id, org_id, team_id, agent_id,
                    tool_name, verdict, detail, trace_id, request_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                entry.boundary,
                entry.user_id,
                entry.org_id,
                entry.team_id,
                entry.agent_id,
                entry.tool_name or "",
                entry.verdict,
                entry.detail,
                entry.trace_id,
                entry.request_id,
            )

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering (org-scoped)."""
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        # Each filter maps a whitelisted column name to its value.
        # Column names are validated against _ALLOWED_FILTER_COLUMNS before
        # interpolation to eliminate any SQL-injection surface.
        filters: list[tuple[str, str]] = []
        if org_id and org_id != "__system__":
            filters.append(("org_id", org_id))
        if user_id:
            filters.append(("user_id", user_id))
        if agent_id:
            filters.append(("agent_id", agent_id))

        for col, value in filters:
            if col not in _ALLOWED_FILTER_COLUMNS:
                raise ValueError(f"Invalid filter column: {col!r}")
            conditions.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        params.append(limit)
        query = f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"  # noqa: S608  # nosec B608 — column names validated against _ALLOWED_FILTER_COLUMNS

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            AuditEntry(
                timestamp=r["timestamp"],
                boundary=r.get("boundary", ""),
                user_id=r.get("user_id", ""),
                org_id=r.get("org_id", ""),
                team_id=r.get("team_id", ""),
                agent_id=r.get("agent_id", ""),
                tool_name=r.get("tool_name"),
                verdict=r.get("verdict", "allowed"),
                detail=r.get("detail", ""),
                trace_id=r.get("trace_id", ""),
                request_id=r.get("request_id", ""),
            )
            for r in rows
        ]
