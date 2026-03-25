"""Quota billing: cycle key generation and daily budget normalization."""

from __future__ import annotations

from datetime import UTC, datetime


def cycle_key(billing_cycle: str) -> str:
    """Generate a cycle key based on billing type."""
    now = datetime.now(UTC)
    if billing_cycle == "daily":
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m")


def daily_budget(free_tokens: int, billing_cycle: str) -> float:
    """Normalize free_tokens to a daily budget."""
    if billing_cycle == "daily":
        return float(free_tokens)
    return float(free_tokens) / 30.0
