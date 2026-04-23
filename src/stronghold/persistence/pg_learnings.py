"""PostgreSQL learning store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.memory import Learning

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("stronghold.persistence.learnings")


class PgLearningStore:
    """PostgreSQL-backed learning store with org isolation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def store(self, learning: Learning) -> int:
        """Store a learning. Dedup by tool_name + org_id + trigger_key overlap."""
        async with self._pool.acquire() as conn:
            # Check dedup: same tool, same org, >50% trigger overlap
            existing = await conn.fetch(
                """SELECT id, trigger_keys FROM learnings
                   WHERE tool_name = $1 AND org_id = $2 AND status = 'active'""",
                learning.tool_name,
                learning.org_id,
            )
            for row in existing:
                existing_keys = set(row["trigger_keys"])
                new_keys = set(learning.trigger_keys)
                if new_keys and existing_keys:
                    overlap = len(new_keys & existing_keys) / len(new_keys)
                    if overlap >= 0.5:
                        await conn.execute(
                            "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = $1",
                            row["id"],
                        )
                        return int(row["id"])

            row = await conn.fetchrow(
                """INSERT INTO learnings
                   (category, trigger_keys, learning, tool_name,
                    org_id, team_id, agent_id, user_id, scope, status,
                    rca_category, rca_prevention,
                    success_after_use, failure_after_use)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                           $11, $12, $13, $14)
                   RETURNING id""",
                learning.category,
                list(learning.trigger_keys),
                learning.learning,
                learning.tool_name,
                learning.org_id,
                learning.team_id,
                learning.agent_id or "",
                learning.user_id,
                learning.scope,
                learning.status,
                learning.rca_category,
                learning.rca_prevention,
                learning.success_after_use,
                learning.failure_after_use,
            )
            return int(row["id"]) if row else 0

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find relevant learnings by keyword match. Org-scoped."""
        if not org_id:
            return []  # System caller sees nothing org-scoped

        async with self._pool.acquire() as conn:
            query = """
                SELECT * FROM learnings
                WHERE status = 'active' AND org_id = $1
            """
            params: list[Any] = [org_id]
            if agent_id:
                query += " AND (agent_id = $2 OR agent_id = '')"
                params.append(agent_id)

            rows = await conn.fetch(query, *params)

        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []
        for row in rows:
            keys: list[str] = row["trigger_keys"] or []
            score = sum(1 for k in keys if k.lower() in text_lower)
            if score > 0:
                scored.append((float(score), _row_to_learning(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for given IDs."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ANY($1::int[])",
                learning_ids,
            )

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success_after_use or failure_after_use per id, org-scoped."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            if success and org_id:
                await conn.execute(
                    "UPDATE learnings SET success_after_use = success_after_use + 1 "
                    "WHERE id = ANY($1::int[]) AND org_id = $2",
                    learning_ids,
                    org_id,
                )
            elif success:
                await conn.execute(
                    "UPDATE learnings SET success_after_use = success_after_use + 1 "
                    "WHERE id = ANY($1::int[])",
                    learning_ids,
                )
            elif org_id:
                await conn.execute(
                    "UPDATE learnings SET failure_after_use = failure_after_use + 1 "
                    "WHERE id = ANY($1::int[]) AND org_id = $2",
                    learning_ids,
                    org_id,
                )
            else:
                await conn.execute(
                    "UPDATE learnings SET failure_after_use = failure_after_use + 1 "
                    "WHERE id = ANY($1::int[])",
                    learning_ids,
                )

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings with hit_count >= threshold."""
        if not org_id:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """UPDATE learnings SET status = 'promoted'
                   WHERE status = 'active' AND hit_count >= $1 AND org_id = $2
                   RETURNING *""",
                threshold,
                org_id,
            )
            return [_row_to_learning(r) for r in rows]

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
    ) -> list[Learning]:
        """Get promoted learnings for an org."""
        if not org_id:
            return []
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM learnings WHERE status = 'promoted' AND org_id = $1"
            params: list[Any] = [org_id]
            if task_type:
                query += " AND category = $2"
                params.append(task_type)
            rows = await conn.fetch(query, *params)
            return [_row_to_learning(r) for r in rows]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings for an org (admin endpoint)."""
        async with self._pool.acquire() as conn:
            if org_id and org_id != "__system__":
                rows = await conn.fetch(
                    "SELECT * FROM learnings WHERE org_id = $1 ORDER BY id DESC LIMIT $2",
                    org_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM learnings ORDER BY id DESC LIMIT $1",
                    limit,
                )
            return [_row_to_learning(r) for r in rows]


def _row_to_learning(row: asyncpg.Record) -> Learning:
    return Learning(
        id=row["id"],
        category=row.get("category", ""),
        trigger_keys=list(row.get("trigger_keys", [])),
        learning=row["learning"],
        tool_name=row.get("tool_name", ""),
        org_id=row.get("org_id", ""),
        team_id=row.get("team_id", ""),
        agent_id=row.get("agent_id") or None,
        user_id=row.get("user_id"),
        scope=row.get("scope", "organization"),
        hit_count=row.get("hit_count", 0),
        status=row.get("status", "active"),
        rca_category=row.get("rca_category"),
        rca_prevention=row.get("rca_prevention", ""),
        success_after_use=row.get("success_after_use", 0),
        failure_after_use=row.get("failure_after_use", 0),
    )
