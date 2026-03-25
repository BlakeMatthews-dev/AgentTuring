"""Quota tracker: token usage recording per provider per billing cycle.

In-memory implementation for testing. PostgreSQL version in later step.
"""

from __future__ import annotations

from collections import defaultdict

from stronghold.quota.billing import cycle_key


class InMemoryQuotaTracker:
    """In-memory quota tracker for testing and local dev."""

    def __init__(self) -> None:
        self._usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_count": 0},
        )

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        """Record token usage."""
        key = (provider, cycle_key(billing_cycle))
        entry = self._usage[key]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["total_tokens"] += input_tokens + output_tokens
        entry["request_count"] += 1
        return {
            "provider": provider,
            "cycle_key": key[1],
            **entry,
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
        key = (provider, cycle_key(billing_cycle))
        entry = self._usage[key]
        return entry["total_tokens"] / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records."""
        result = []
        for (provider, ck), entry in self._usage.items():
            result.append({"provider": provider, "cycle_key": ck, **entry})
        return result
