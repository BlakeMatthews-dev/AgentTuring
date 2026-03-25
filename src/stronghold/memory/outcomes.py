"""Outcome store: in-memory implementation.

Tracks request outcomes for task completion rate analysis
and experience-augmented prompts. Same API as Conductor's
record_outcome() / get_task_completion_rate().

PostgreSQL version would use asyncpg with an outcomes table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.types.memory import Outcome

MAX_OUTCOMES = 10000  # FIFO cap to prevent OOM


class InMemoryOutcomeStore:
    """In-memory outcome store for testing and local dev."""

    def __init__(self, max_outcomes: int = MAX_OUTCOMES) -> None:
        self._outcomes: list[Outcome] = []
        self._next_id = 1
        self._max_outcomes = max_outcomes

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome. Returns outcome ID. FIFO eviction at cap."""
        if len(self._outcomes) >= self._max_outcomes:
            self._outcomes.pop(0)
        outcome.id = self._next_id
        self._next_id += 1
        self._outcomes.append(outcome)
        return outcome.id

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> dict[str, Any]:
        """Get completion rate stats, org-scoped."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff
            and (not task_type or o.task_type == task_type)
            and self._matches_org(o.org_id, org_id)
        ]

        total = len(filtered)
        succeeded = sum(1 for o in filtered if o.success)
        failed = total - succeeded

        by_model: dict[str, dict[str, Any]] = {}
        for o in filtered:
            if o.model_used not in by_model:
                by_model[o.model_used] = {"total": 0, "succeeded": 0}
            by_model[o.model_used]["total"] += 1
            if o.success:
                by_model[o.model_used]["succeeded"] += 1

        for stats in by_model.values():
            stats["rate"] = stats["succeeded"] / max(stats["total"], 1)

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "rate": succeeded / max(total, 1),
            "by_model": by_model,
            "days": days,
            "task_type": task_type or "all",
        }

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
    ) -> str:
        """Get recent failure patterns as a prompt section (org-scoped)."""
        cutoff = datetime.now(UTC) - timedelta(days=7)

        failures = [
            o
            for o in self._outcomes
            if not o.success
            and o.task_type == task_type
            and o.created_at >= cutoff
            and (not tool_name or any(tc.get("name") == tool_name for tc in o.tool_calls))
            and self._matches_org(o.org_id, org_id)
        ]

        if not failures:
            return ""

        failures = failures[-limit:]
        lines = ["## Recent Failure Patterns"]
        for o in failures:
            error = o.error_type or "unknown"
            lines.append(f"- {error} (model: {o.model_used})")

        return "\n".join(lines)

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff and self._matches_org(o.org_id, org_id)
        ]

        groups: dict[str, dict[str, Any]] = {}
        for o in filtered:
            key = getattr(o, group_by, "") or "(unknown)"
            if key not in groups:
                groups[key] = {
                    "group": key,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "request_count": 0,
                    "success_count": 0,
                    "total_microchips": 0,
                    "avg_response_ms": 0.0,
                    "_total_ms": 0,
                }
            g = groups[key]
            g["input_tokens"] += o.input_tokens
            g["output_tokens"] += o.output_tokens
            g["total_tokens"] += o.input_tokens + o.output_tokens
            g["total_microchips"] += getattr(o, "charged_microchips", 0)
            g["request_count"] += 1
            if o.success:
                g["success_count"] += 1
            g["_total_ms"] += o.response_time_ms

        result = []
        for g in groups.values():
            if g["request_count"] > 0:
                g["avg_response_ms"] = round(g["_total_ms"] / g["request_count"], 1)
            del g["_total_ms"]
            result.append(g)

        result.sort(key=lambda x: x["total_tokens"], reverse=True)
        return result

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries, optionally grouped."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff and self._matches_org(o.org_id, org_id)
        ]

        buckets: dict[str, dict[str, Any]] = {}
        for o in filtered:
            day_str = o.created_at.strftime("%Y-%m-%d")
            grp = getattr(o, group_by, "") if group_by else "__all__"
            key = f"{day_str}|{grp}"
            if key not in buckets:
                buckets[key] = {
                    "date": day_str,
                    "group": grp if group_by else None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "total_microchips": 0,
                    "request_count": 0,
                }
            b = buckets[key]
            b["input_tokens"] += o.input_tokens
            b["output_tokens"] += o.output_tokens
            b["total_tokens"] += o.input_tokens + o.output_tokens
            b["total_microchips"] += getattr(o, "charged_microchips", 0)
            b["request_count"] += 1

        result = sorted(buckets.values(), key=lambda x: x["date"])
        return result

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
        org_id: str = "",
    ) -> list[Outcome]:
        """List recent outcomes (org-scoped)."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff
            and (not task_type or o.task_type == task_type)
            and self._matches_org(o.org_id, org_id)
        ]
        return filtered[-limit:]

    @staticmethod
    def _matches_org(record_org: str, caller_org: str) -> bool:
        """Strict org matching: both must agree or both must be empty."""
        if caller_org:
            return record_org == caller_org
        # System caller (no org): only see unscoped records
        return not record_org
