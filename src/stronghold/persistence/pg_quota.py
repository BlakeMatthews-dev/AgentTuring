"""PostgreSQL quota tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.quota.billing import cycle_key

if TYPE_CHECKING:
    import asyncpg


class PgQuotaTracker:
    """PostgreSQL-backed quota tracker."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        """Record token usage."""
        ck = cycle_key(billing_cycle)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO quota_usage
                   (provider, cycle_key, input_tokens, output_tokens,
                    total_tokens, request_count)
                   VALUES ($1, $2, $3, $4, $5, 1)
                   ON CONFLICT (provider, cycle_key) DO UPDATE SET
                     input_tokens = quota_usage.input_tokens + $3,
                     output_tokens = quota_usage.output_tokens + $4,
                     total_tokens = quota_usage.total_tokens + $5,
                     request_count = quota_usage.request_count + 1
                   RETURNING *""",
                provider,
                ck,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
            )
        return {
            "provider": provider,
            "cycle_key": ck,
            "input_tokens": row["input_tokens"] if row else 0,
            "output_tokens": row["output_tokens"] if row else 0,
            "total_tokens": row["total_tokens"] if row else 0,
            "request_count": row["request_count"] if row else 0,
        }

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        """Get usage as a percentage of free tier."""
        if free_tokens <= 0:
            return 0.0
        ck = cycle_key(billing_cycle)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT total_tokens FROM quota_usage WHERE provider = $1 AND cycle_key = $2",
                provider,
                ck,
            )
        total: int = row["total_tokens"] if row else 0
        return total / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM quota_usage ORDER BY provider, cycle_key",
            )
        return [
            {
                "provider": r["provider"],
                "cycle_key": r["cycle_key"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "total_tokens": r["total_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]
