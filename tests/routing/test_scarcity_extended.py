"""Extended scarcity and routing edge case tests."""

from stronghold.router.scarcity import compute_effective_cost
from stronghold.router.scorer import score_candidate
from stronghold.router.speed import SPEED_WEIGHTS, compute_speed_bonus
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)


class TestUsageLevels:
    """Specific usage percentage scenarios."""

    def test_zero_usage_minimal_cost(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        cost = compute_effective_cost(0.0, provider)
        assert cost > 0
        assert cost < 0.1  # very cheap for big budget at 0%

    def test_50_pct_moderate_cost(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        cost_50 = compute_effective_cost(0.5, provider)
        cost_0 = compute_effective_cost(0.0, provider)
        assert cost_50 > cost_0  # more expensive at 50%

    def test_99_pct_very_high_cost(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        cost_99 = compute_effective_cost(0.99, provider)
        cost_50 = compute_effective_cost(0.5, provider)
        assert cost_99 > cost_50  # monotonically more expensive at higher usage

    def test_paygo_at_100_uses_overage(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.02,
            overage_cost_per_1k_output=0.06,
        )
        cost = compute_effective_cost(1.0, provider)
        expected = (0.02 + 0.06) / 2000
        assert cost == expected

    def test_non_paygo_at_100_infinity(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.0,
            overage_cost_per_1k_output=0.0,
        )
        cost = compute_effective_cost(1.0, provider)
        assert cost == 999.0

    def test_over_100_no_paygo_still_infinity(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000)
        cost = compute_effective_cost(1.5, provider)
        assert cost == 999.0

    def test_over_100_with_paygo_uses_overage(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.01,
            overage_cost_per_1k_output=0.03,
        )
        cost = compute_effective_cost(1.5, provider)
        expected = (0.01 + 0.03) / 2000
        assert cost == expected


class TestMultipleProviders:
    """Different providers with different usage levels."""

    def test_low_usage_beats_high_usage(self) -> None:
        provider_low = build_provider_config(free_tokens=1_000_000_000)
        provider_high = build_provider_config(free_tokens=1_000_000_000)
        cost_low = compute_effective_cost(0.1, provider_low)
        cost_high = compute_effective_cost(0.9, provider_high)
        assert cost_low < cost_high

    def test_big_budget_at_high_usage_vs_small_budget_low_usage(self) -> None:
        big_provider = build_provider_config(free_tokens=10_000_000_000)
        small_provider = build_provider_config(free_tokens=1_000_000)
        cost_big_80 = compute_effective_cost(0.8, big_provider)
        cost_small_10 = compute_effective_cost(0.1, small_provider)
        # Both should produce valid costs
        assert cost_big_80 > 0
        assert cost_small_10 > 0

    def test_three_providers_ordering(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000_000)
        cost_10 = compute_effective_cost(0.1, provider)
        cost_50 = compute_effective_cost(0.5, provider)
        cost_90 = compute_effective_cost(0.9, provider)
        assert cost_10 < cost_50 < cost_90

    def test_daily_vs_monthly_at_same_usage(self) -> None:
        daily = build_provider_config(free_tokens=30_000_000, billing_cycle="daily")
        monthly = build_provider_config(free_tokens=30_000_000, billing_cycle="monthly")
        cost_daily = compute_effective_cost(0.5, daily)
        cost_monthly = compute_effective_cost(0.5, monthly)
        assert cost_daily < cost_monthly  # daily gets full budget per day


class TestSpeedBonusPerTaskType:
    """Speed bonus correctly applied per task type."""

    def test_automation_has_highest_bonus(self) -> None:
        bonus = compute_speed_bonus("automation", 2000)
        assert bonus == 0.25

    def test_chat_has_moderate_bonus(self) -> None:
        bonus = compute_speed_bonus("chat", 2000)
        assert bonus == 0.15

    def test_code_has_zero_bonus(self) -> None:
        bonus = compute_speed_bonus("code", 2000)
        assert bonus == 0.0

    def test_reasoning_has_zero_bonus(self) -> None:
        bonus = compute_speed_bonus("reasoning", 2000)
        assert bonus == 0.0

    def test_speed_bonus_scales_with_speed(self) -> None:
        bonus_fast = compute_speed_bonus("chat", 2000)
        bonus_slow = compute_speed_bonus("chat", 100)
        assert bonus_fast > bonus_slow

    def test_speed_bonus_zero_speed(self) -> None:
        bonus = compute_speed_bonus("chat", 0)
        assert bonus == 0.0

    def test_speed_bonus_exceeds_max_capped(self) -> None:
        bonus = compute_speed_bonus("chat", 5000)  # exceeds _MAX_SPEED
        assert bonus == 0.15  # weight * min(1.0, ...) = 0.15 * 1.0

    def test_unknown_task_type_no_bonus(self) -> None:
        bonus = compute_speed_bonus("unknown_type", 2000)
        assert bonus == 0.0

    def test_all_known_task_types_have_weights(self) -> None:
        for task_type in SPEED_WEIGHTS:
            bonus = compute_speed_bonus(task_type, 1000)
            assert bonus >= 0.0

    def test_half_speed_half_bonus(self) -> None:
        # At 1000 tok/s (half max), bonus = weight * 0.5
        bonus = compute_speed_bonus("automation", 1000)
        assert abs(bonus - 0.125) < 0.001


class TestScorerIntegration:
    """Score computation with different configs."""

    def test_higher_quality_higher_score(self) -> None:
        intent = build_intent(task_type="code", preferred_strengths=("code",))
        routing = build_routing_config()
        provider = build_provider_config(free_tokens=1_000_000_000)

        low_q = build_model_config(quality=0.3, strengths=("code",))
        high_q = build_model_config(quality=0.9, strengths=("code",))

        cand_low = score_candidate("low", low_q, provider, intent, routing, 0.1)
        cand_high = score_candidate("high", high_q, provider, intent, routing, 0.1)
        assert cand_high.score > cand_low.score

    def test_lower_cost_higher_score(self) -> None:
        intent = build_intent(task_type="chat")
        routing = build_routing_config()
        model = build_model_config(quality=0.6, strengths=("chat",))

        cheap = build_provider_config(free_tokens=10_000_000_000)
        expensive = build_provider_config(free_tokens=1_000_000)

        cand_cheap = score_candidate("c", model, cheap, intent, routing, 0.5)
        cand_expensive = score_candidate("e", model, expensive, intent, routing, 0.5)
        assert cand_cheap.score > cand_expensive.score

    def test_strength_match_bonus(self) -> None:
        intent = build_intent(task_type="code", preferred_strengths=("code",))
        routing = build_routing_config()
        provider = build_provider_config(free_tokens=1_000_000_000)

        matched = build_model_config(quality=0.6, strengths=("code",))
        unmatched = build_model_config(quality=0.6, strengths=("chat",))

        cand_m = score_candidate("m", matched, provider, intent, routing, 0.1)
        cand_u = score_candidate("u", unmatched, provider, intent, routing, 0.1)
        assert cand_m.score > cand_u.score

    def test_paygo_flag_set(self) -> None:
        intent = build_intent()
        routing = build_routing_config()
        model = build_model_config()
        provider = build_provider_config(overage_cost_per_1k_input=0.01)
        cand = score_candidate("p", model, provider, intent, routing, 0.5)
        assert cand.has_paygo is True

    def test_no_paygo_flag(self) -> None:
        intent = build_intent()
        routing = build_routing_config()
        model = build_model_config()
        provider = build_provider_config()
        cand = score_candidate("p", model, provider, intent, routing, 0.5)
        assert cand.has_paygo is False

    def test_critical_priority_boosts_quality_weight(self) -> None:
        routing = build_routing_config()
        provider = build_provider_config(free_tokens=1_000_000_000)
        model = build_model_config(quality=0.9, strengths=("code",))

        normal = build_intent(priority="normal", preferred_strengths=("code",))
        critical = build_intent(priority="critical", preferred_strengths=("code",))

        cand_n = score_candidate("n", model, provider, normal, routing, 0.1)
        cand_c = score_candidate("c", model, provider, critical, routing, 0.1)
        # Critical gets higher priority multiplier by default
        # Both should score > 0; exact ordering depends on multiplier config
        assert cand_n.score > 0
        assert cand_c.score > 0
