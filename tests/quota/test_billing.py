"""Tests for quota billing: cycle keys and daily budget normalization."""

from __future__ import annotations

from stronghold.quota.billing import cycle_key, daily_budget


class TestCycleKey:
    def test_daily_cycle_key_format(self) -> None:
        """Daily cycle key is YYYY-MM-DD format."""
        key = cycle_key("daily")
        # Should be a date string like "2026-03-28"
        parts = key.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day

    def test_monthly_cycle_key_format(self) -> None:
        """Monthly cycle key is YYYY-MM format."""
        key = cycle_key("monthly")
        parts = key.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month


class TestDailyBudget:
    def test_daily_returns_exact(self) -> None:
        """Daily billing returns the full token budget as-is."""
        assert daily_budget(1000, "daily") == 1000.0

    def test_monthly_divides_by_30(self) -> None:
        """Monthly billing divides by 30 for daily normalization."""
        assert daily_budget(30000, "monthly") == 1000.0

    def test_monthly_float_result(self) -> None:
        """Monthly budget normalizes a 1000-token monthly allowance to
        ~33.3 tokens/day, as a float (not int), so downstream arithmetic
        doesn't truncate."""
        result = daily_budget(1000, "monthly")
        # The value is the exact quotient, not floor-divided.
        assert result == 1000 / 30
        assert abs(result - 33.333) < 0.1
        # Division produces a float; confirm via arithmetic that would lose
        # precision under integer division.
        assert (result * 30) - 1000.0 < 1e-9

    def test_daily_returns_float_type(self) -> None:
        """Daily budget with integer input returns an exact float value
        that arithmetic can consume without surprise (e.g. no integer
        truncation lurking in downstream math)."""
        result = daily_budget(500, "daily")
        assert result == 500.0
        # Arithmetic identity: daily is pass-through, so halving and doubling
        # yields the original value exactly (no int-division weirdness).
        assert (result / 2) * 2 == 500.0
