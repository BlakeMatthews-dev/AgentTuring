"""Quota tracker protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class QuotaTracker(Protocol):
    """Tracks token usage per provider per billing cycle."""

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        """Record token usage. Returns updated totals."""
        ...

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        """Get usage as a percentage of free tier (0.0 to 1.0+)."""
        ...

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records for dashboard."""
        ...
