"""Tests for quota reserve enforcement."""

from stronghold.router.filter import filter_candidates
from tests.factories import build_intent, build_model_config, build_provider_config


class TestQuotaReserve:
    def test_blocks_non_critical_above_reserve(self) -> None:
        intent = build_intent(priority="normal")
        models = {"m": build_model_config(provider="p")}
        providers = {"p": build_provider_config(free_tokens=1_000_000)}
        # 96% usage — above 95% reserve threshold
        result = filter_candidates(
            intent, models, providers, usage_pcts={"p": 0.96}, reserve_pct=0.05
        )
        assert len(result) == 0

    def test_allows_critical_above_reserve(self) -> None:
        intent = build_intent(priority="critical")
        models = {"m": build_model_config(provider="p")}
        providers = {"p": build_provider_config(free_tokens=1_000_000)}
        result = filter_candidates(
            intent, models, providers, usage_pcts={"p": 0.96}, reserve_pct=0.05
        )
        assert len(result) == 1

    def test_paygo_bypasses_at_100_percent(self) -> None:
        intent = build_intent(priority="normal")
        models = {"m": build_model_config(provider="p")}
        providers = {
            "p": build_provider_config(
                free_tokens=1_000_000,
                overage_cost_per_1k_input=0.01,
                overage_cost_per_1k_output=0.03,
            )
        }
        result = filter_candidates(
            intent, models, providers, usage_pcts={"p": 1.1}, reserve_pct=0.05
        )
        assert len(result) == 1
