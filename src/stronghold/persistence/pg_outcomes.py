"""PostgreSQL outcome store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from stronghold.types.memory import Outcome

if TYPE_CHECKING:
    import asyncpg


class PgOutcomeStore:
    """PostgreSQL-backed outcome store with org isolation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome. Returns outcome ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO outcomes
                   (request_id, task_type, model_used, provider,
                    tool_calls, success, error_type, response_time_ms,
                    org_id, team_id, user_id, agent_id,
                    input_tokens, output_tokens, charged_microchips, pricing_version)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                   RETURNING id""",
                outcome.request_id,
                outcome.task_type,
                outcome.model_used,
                outcome.provider,
                str(outcome.tool_calls),
                outcome.success,
                outcome.error_type,
                outcome.response_time_ms,
                outcome.org_id,
                outcome.team_id,
                outcome.user_id,
                outcome.agent_id or "",
                outcome.input_tokens,
                outcome.output_tokens,
                outcome.charged_microchips,
                outcome.pricing_version,
            )
            return int(row["id"]) if row else 0

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> dict[str, Any]:
        """Get completion rate stats, org-scoped."""
        if not org_id:
            return {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "rate": 0.0,
                "by_model": {},
                "days": days,
                "task_type": task_type or "all",
            }

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM outcomes WHERE org_id = $1 AND created_at >= $2"
            params: list[Any] = [org_id, cutoff]
            if task_type:
                query += " AND task_type = $3"
                params.append(task_type)
            rows = await conn.fetch(query, *params)

        total = len(rows)
        succeeded = sum(1 for r in rows if r["success"])
        by_model: dict[str, dict[str, Any]] = {}
        for r in rows:
            m: str = r["model_used"]
            if m not in by_model:
                by_model[m] = {"total": 0, "succeeded": 0, "rate": 0.0}
            by_model[m]["total"] += 1
            if r["success"]:
                by_model[m]["succeeded"] += 1
        for v in by_model.values():
            v["rate"] = v["succeeded"] / v["total"] if v["total"] else 0.0

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "rate": succeeded / total if total else 0.0,
            "by_model": by_model,
            "days": days,
            "task_type": task_type or "all",
        }

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension (SQL GROUP BY)."""
        allowed = {"user_id", "team_id", "org_id", "model_used", "agent_id", "provider"}
        if group_by not in allowed:
            group_by = "user_id"

        if not org_id:
            return []

        select_cols = f"""SELECT {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                       ROUND(AVG(response_time_ms)::numeric, 1) AS avg_response_ms
                   FROM outcomes"""

        async with self._pool.acquire() as conn:
            if days > 0:
                cutoff = datetime.now(UTC) - timedelta(days=days)
                rows = await conn.fetch(
                    f"""{select_cols}
                       WHERE org_id = $1 AND created_at >= $2
                       GROUP BY {group_by}
                       ORDER BY total_tokens DESC""",  # noqa: S608
                    org_id,
                    cutoff,
                )
            else:
                rows = await conn.fetch(
                    f"""{select_cols}
                       WHERE org_id = $1
                       GROUP BY {group_by}
                       ORDER BY total_tokens DESC""",  # noqa: S608
                    org_id,
                )

        return [
            {
                "group": r["grp"] or "(unknown)",
                "input_tokens": int(r["input_tokens"]),
                "output_tokens": int(r["output_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "total_microchips": int(r["total_microchips"]),
                "request_count": int(r["request_count"]),
                "success_count": int(r["success_count"]),
                "avg_response_ms": float(r["avg_response_ms"] or 0),
            }
            for r in rows
        ]

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries, optionally grouped by a dimension."""
        if not org_id:
            return []

        allowed = {"user_id", "team_id", "org_id", "model_used", "agent_id", "provider"}
        has_group = group_by in allowed
        cutoff = datetime.now(UTC) - timedelta(days=days)

        if has_group:
            query = f"""
                SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
                       {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                FROM outcomes
                WHERE org_id = $1 AND created_at >= $2
                GROUP BY day, {group_by}
                ORDER BY day"""  # noqa: S608
        else:
            query = """
                SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                FROM outcomes
                WHERE org_id = $1 AND created_at >= $2
                GROUP BY day
                ORDER BY day"""

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, org_id, cutoff)

        return [
            {
                "date": str(r["day"]),
                "group": r["grp"] if has_group else None,
                "input_tokens": int(r["input_tokens"]),
                "output_tokens": int(r["output_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "total_microchips": int(r["total_microchips"]),
                "request_count": int(r["request_count"]),
            }
            for r in rows
        ]

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
    ) -> str:
        """Get recent failure patterns as a prompt section (org-scoped)."""
        if not org_id:
            return ""
        cutoff = datetime.now(UTC) - timedelta(days=7)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM outcomes
                   WHERE org_id = $1 AND task_type = $2 AND success = false
                   AND created_at >= $3
                   ORDER BY created_at DESC LIMIT $4""",
                org_id,
                task_type,
                cutoff,
                limit,
            )
        if not rows:
            return ""
        lines = ["Recent failures:"]
        for r in rows:
            lines.append(f"- {r['error_type']}: model={r['model_used']}")
        return "\n".join(lines)

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
        org_id: str = "",
    ) -> list[Outcome]:
        """List recent outcomes (org-scoped)."""
        if not org_id:
            return []
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM outcomes WHERE org_id = $1 AND created_at >= $2"
            params: list[Any] = [org_id, cutoff]
            if task_type:
                query += " AND task_type = $3"
                params.append(task_type)
            query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
            params.append(limit)
            rows = await conn.fetch(query, *params)

        return [
            Outcome(
                id=r["id"],
                request_id=r.get("request_id", ""),
                task_type=r.get("task_type", ""),
                model_used=r.get("model_used", ""),
                success=r["success"],
                error_type=r.get("error_type", ""),
                response_time_ms=r.get("response_time_ms", 0),
                org_id=r.get("org_id", ""),
                team_id=r.get("team_id", ""),
                user_id=r.get("user_id", ""),
                agent_id=r.get("agent_id") or None,
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                charged_microchips=r.get("charged_microchips", 0),
                pricing_version=r.get("pricing_version", ""),
                created_at=r.get("created_at", datetime.now(UTC)),
            )
            for r in rows
        ]
