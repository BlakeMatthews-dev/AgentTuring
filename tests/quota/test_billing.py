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
        """Monthly budget returns a float even when not evenly divisible."""
        result = daily_budget(1000, "monthly")
        assert isinstance(result, float)
        assert abs(result - 33.333) < 0.1

    def test_daily_returns_float_type(self) -> None:
        """Daily budget returns float type even for integer input."""
        result = daily_budget(500, "daily")
        assert isinstance(result, float)
        assert result == 500.0
