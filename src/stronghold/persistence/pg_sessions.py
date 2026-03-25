"""PostgreSQL session store."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


class PgSessionStore:
    """PostgreSQL-backed session store."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        max_messages: int = 20,
        ttl_seconds: int = 86400,
    ) -> None:
        self._pool = pool
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        max_msg = max_messages or self._max_messages
        ttl = ttl_seconds or self._ttl_seconds
        cutoff = time.time() - ttl

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content FROM sessions
                   WHERE session_id = $1 AND timestamp > to_timestamp($2)
                   ORDER BY seq DESC LIMIT $3""",
                session_id,
                cutoff,
                max_msg,
            )
        rows = list(reversed(rows))
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to session history."""
        async with self._pool.acquire() as conn:
            # Get next seq for this session
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM sessions WHERE session_id = $1",
                session_id,
            )
            next_seq: int = row["next_seq"] if row else 0

            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    await conn.execute(
                        """INSERT INTO sessions (session_id, seq, role, content)
                           VALUES ($1, $2, $3, $4)""",
                        session_id,
                        next_seq,
                        role,
                        content,
                    )
                    next_seq += 1

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE session_id = $1",
                session_id,
            )
