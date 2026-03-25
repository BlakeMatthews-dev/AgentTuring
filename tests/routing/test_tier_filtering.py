"""Tests for tier-based model filtering."""

from stronghold.router.filter import filter_candidates
from tests.factories import build_intent, build_model_config, build_provider_config


class TestMinTier:
    def test_rejects_below_min_tier(self) -> None:
        intent = build_intent(min_tier="medium")
        models = {"small-model": build_model_config(tier="small", provider="p")}
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 0

    def test_accepts_at_min_tier(self) -> None:
        intent = build_intent(min_tier="medium")
        models = {"med-model": build_model_config(tier="medium", provider="p")}
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 1


class TestMaxTier:
    def test_rejects_above_max_tier(self) -> None:
        intent = build_intent(min_tier="small", max_tier="medium")
        models = {"big-model": build_model_config(tier="frontier", provider="p")}
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 0


class TestInactiveProvider:
    def test_inactive_provider_filtered(self) -> None:
        intent = build_intent()
        models = {"m": build_model_config(provider="dead")}
        providers = {"dead": build_provider_config(status="inactive")}
        result = filter_candidates(intent, models, providers, usage_pcts={"dead": 0.0})
        assert len(result) == 0

    def test_missing_provider_filtered(self) -> None:
        intent = build_intent()
        models = {"m": build_model_config(provider="nonexistent")}
        providers = {}
        result = filter_candidates(intent, models, providers, usage_pcts={})
        assert len(result) == 0

    def test_active_provider_passes(self) -> None:
        intent = build_intent()
        models = {"m": build_model_config(provider="p")}
        providers = {"p": build_provider_config(status="active")}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 1


class TestMultipleModels:
    def test_filters_multiple_models(self) -> None:
        intent = build_intent(min_tier="medium")
        models = {
            "small-m": build_model_config(tier="small", provider="p"),
            "medium-m": build_model_config(tier="medium", provider="p"),
            "large-m": build_model_config(tier="large", provider="p"),
        }
        providers = {"p": build_provider_config()}
        result = filter_candidates(intent, models, providers, usage_pcts={"p": 0.0})
        assert len(result) == 2  # medium + large, not small
        names = [r[0] for r in result]
        assert "small-m" not in names
