"""Tests for scarcity-based effective cost computation.

Properties:
- Cost monotonically increases with usage_pct (0.0 → 0.99)
- Bigger budget (more free_tokens) → lower cost at same usage_pct
- At 0% usage: cost = 1/ln(daily_budget)
- At >=100% without paygo: cost = 999.0
- At >=100% with paygo: cost = average overage rate
- Zero free tokens: cost = 1.0
"""

from stronghold.router.scarcity import compute_effective_cost
from tests.factories import build_provider_config


class TestMonotonicity:
    """Cost should increase monotonically as usage increases."""

    def test_cost_increases_with_usage(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        costs = [compute_effective_cost(pct / 100.0, provider) for pct in range(0, 100, 5)]
        for i in range(1, len(costs)):
            assert costs[i] >= costs[i - 1], (
                f"Cost decreased at {i * 5}%: {costs[i]} < {costs[i - 1]}"
            )


class TestBudgetSensitivity:
    """Bigger budget should mean lower cost at same usage percentage."""

    def test_bigger_budget_lower_cost(self) -> None:
        big = build_provider_config(free_tokens=1_000_000_000)
        small = build_provider_config(free_tokens=1_000_000)
        assert compute_effective_cost(0.5, big) < compute_effective_cost(0.5, small)


class TestBoundaryConditions:
    """Edge cases at 0%, 100%, and zero budget."""

    def test_at_zero_usage(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        cost = compute_effective_cost(0.0, provider)
        assert cost > 0.0
        assert cost < 1.0  # big budget should be cheap

    def test_at_100_percent_no_paygo(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000, overage_cost_per_1k_input=0.0)
        cost = compute_effective_cost(1.0, provider)
        assert cost == 999.0

    def test_at_100_percent_with_paygo(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.01,
            overage_cost_per_1k_output=0.03,
        )
        cost = compute_effective_cost(1.0, provider)
        expected = (0.01 + 0.03) / 2000  # average per-token cost
        assert cost == expected

    def test_zero_free_tokens(self) -> None:
        provider = build_provider_config(free_tokens=0)
        cost = compute_effective_cost(0.0, provider)
        assert cost == 1.0

    def test_cost_always_positive(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        for pct in [0.0, 0.25, 0.5, 0.75, 0.99]:
            assert compute_effective_cost(pct, provider) > 0.0


class TestScarcityCurveEdgeCases:
    def test_very_small_budget(self) -> None:
        provider = build_provider_config(free_tokens=100)
        cost = compute_effective_cost(0.0, provider)
        assert cost > 0

    def test_very_large_budget(self) -> None:
        provider = build_provider_config(free_tokens=10_000_000_000)
        cost = compute_effective_cost(0.0, provider)
        assert cost > 0
        assert cost < 0.1  # very cheap

    def test_at_99_percent(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000)
        cost = compute_effective_cost(0.99, provider)
        assert cost > compute_effective_cost(0.5, provider)

    def test_daily_provider(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000, billing_cycle="daily")
        cost = compute_effective_cost(0.5, provider)
        assert cost > 0

    def test_monthly_is_cheaper_than_daily_same_tokens(self) -> None:
        monthly = build_provider_config(free_tokens=1_000_000, billing_cycle="monthly")
        daily = build_provider_config(free_tokens=1_000_000, billing_cycle="daily")
        # Monthly divides by 30, so daily has 30x more budget per day
        assert compute_effective_cost(0.5, daily) < compute_effective_cost(0.5, monthly)

    def test_overage_cost_proportional(self) -> None:
        cheap = build_provider_config(
            overage_cost_per_1k_input=0.001, overage_cost_per_1k_output=0.001
        )
        expensive = build_provider_config(
            overage_cost_per_1k_input=0.1, overage_cost_per_1k_output=0.1
        )
        assert compute_effective_cost(1.0, cheap) < compute_effective_cost(1.0, expensive)


class TestScarcityCurveRanges:
    def test_cost_range_0_to_50_pct(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        costs = [compute_effective_cost(p / 100.0, provider) for p in range(0, 51)]
        for c in costs:
            assert 0 < c < 1.0

    def test_cost_range_50_to_99_pct(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000)
        costs = [compute_effective_cost(p / 100.0, provider) for p in range(50, 100)]
        for c in costs:
            assert c > 0
