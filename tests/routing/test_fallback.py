"""Tests for fallback behavior when no candidates match filters."""

import pytest

from stronghold.router.selector import RouterEngine
from stronghold.types.errors import QuotaReserveError
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)
from tests.fakes import FakeQuotaTracker


class TestFallback:
    def test_fallback_to_highest_quality_active_model(self) -> None:
        engine = RouterEngine(FakeQuotaTracker(usage_pct=0.0))
        intent = build_intent(min_tier="frontier")
        models = {
            "small-good": build_model_config(tier="small", quality=0.8, provider="p"),
            "medium-ok": build_model_config(tier="medium", quality=0.5, provider="p"),
        }
        providers = {"p": build_provider_config()}
        config = build_routing_config()
        # No frontier models exist — should fallback
        result = engine.select(intent, models, providers, config)
        assert result.model_id == "small-good"  # highest quality
        assert result.score == 0.0  # fallback marker

    def test_raises_when_all_in_reserve(self) -> None:
        engine = RouterEngine(FakeQuotaTracker(usage_pct=0.96))
        intent = build_intent(tier="P2")
        models = {"m": build_model_config(provider="p")}
        providers = {"p": build_provider_config(free_tokens=1_000_000)}
        config = build_routing_config()
        with pytest.raises(QuotaReserveError):
            engine.select_with_usage(intent, models, providers, config, {"p": 0.96})
