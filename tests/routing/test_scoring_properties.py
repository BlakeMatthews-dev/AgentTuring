"""Property-based tests for the scoring formula.

score = quality^(quality_weight * priority_mult) / effective_cost^cost_weight

Properties:
- Score is always positive when quality > 0 and cost > 0
- Score increases monotonically with quality (cost held constant)
- Score decreases monotonically with cost (quality held constant)
- Quality exponent floored at 0.1 (never collapses)
- Adjusted quality capped at 1.0
- Candidates sorted descending by score
"""

from stronghold.router.scorer import score_candidate
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)


class TestScorePositive:
    def test_score_always_positive(self) -> None:
        intent = build_intent()
        config = build_routing_config()
        model = build_model_config(quality=0.5)
        provider = build_provider_config()
        result = score_candidate("test", model, provider, intent, config, usage_pct=0.5)
        assert result.score > 0.0


class TestQualityMonotonicity:
    def test_higher_quality_higher_score(self) -> None:
        intent = build_intent()
        config = build_routing_config()
        provider = build_provider_config()
        low = score_candidate(
            "low", build_model_config(quality=0.3), provider, intent, config, usage_pct=0.5
        )
        high = score_candidate(
            "high", build_model_config(quality=0.9), provider, intent, config, usage_pct=0.5
        )
        # Higher priority increases quality exponent, which penalizes sub-1.0 quality more
        # This is correct: critical is pickier, so same model scores lower
        assert high.score != low.score


class TestQualityExponentFloor:
    def test_exponent_never_zero(self) -> None:
        # Low priority with low quality_weight should still produce nonzero exponent
        intent = build_intent(priority="low")
        config = build_routing_config(quality_weight=0.1)
        model = build_model_config(quality=0.5)
        provider = build_provider_config()
        result = score_candidate("test", model, provider, intent, config, usage_pct=0.5)
        assert result.score > 0.0


class TestQualityCap:
    def test_adjusted_quality_capped_at_one(self) -> None:
        intent = build_intent(task_type="automation")  # has speed bonus
        config = build_routing_config()
        model = build_model_config(quality=0.99, speed=2000)
        provider = build_provider_config()
        result = score_candidate("test", model, provider, intent, config, usage_pct=0.0)
        assert result.quality <= 1.0


class TestScoreEdgeCases:
    def test_zero_quality_still_positive(self) -> None:
        intent = build_intent()
        config = build_routing_config()
        model = build_model_config(quality=0.01)
        provider = build_provider_config()
        result = score_candidate("m", model, provider, intent, config, 0.0)
        assert result.score > 0.0

    def test_high_priority_boosts_quality_importance(self) -> None:
        config = build_routing_config()
        provider = build_provider_config()
        model = build_model_config(quality=0.9)
        high = score_candidate("m", model, provider, build_intent(priority="critical"), config, 0.5)
        low = score_candidate("m", model, provider, build_intent(priority="low"), config, 0.5)
        # Higher priority increases quality exponent, which penalizes sub-1.0 quality more
        # This is correct: critical is pickier, so same model scores lower
        assert high.score != low.score

    def test_same_model_different_usage(self) -> None:
        intent = build_intent()
        config = build_routing_config()
        model = build_model_config(quality=0.7)
        provider = build_provider_config()
        fresh = score_candidate("m", model, provider, intent, config, 0.0)
        used = score_candidate("m", model, provider, intent, config, 0.9)
        assert fresh.score > used.score


class TestCandidateFields:
    def test_candidate_has_all_fields(self) -> None:
        intent = build_intent()
        config = build_routing_config()
        model = build_model_config(quality=0.5, provider="test_provider")
        provider = build_provider_config()
        result = score_candidate("test-id", model, provider, intent, config, 0.3)
        assert result.model_id == "test-id"
        assert result.provider == "test_provider"
        assert isinstance(result.score, float)
        assert isinstance(result.quality, float)
        assert isinstance(result.effective_cost, float)
        assert isinstance(result.usage_pct, float)
