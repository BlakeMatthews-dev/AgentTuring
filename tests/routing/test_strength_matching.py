"""Tests for strength-based quality multiplier."""

from stronghold.router.scorer import score_candidate
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)


class TestStrengthMatching:
    def test_matching_strengths_boost(self) -> None:
        intent = build_intent(preferred_strengths=("code",))
        config = build_routing_config()
        provider = build_provider_config()

        match = score_candidate(
            "m", build_model_config(strengths=("code",), quality=0.5), provider, intent, config, 0.0
        )
        no_match = score_candidate(
            "m",
            build_model_config(strengths=("creative",), quality=0.5),
            provider,
            intent,
            config,
            0.0,
        )
        assert match.score > no_match.score

    def test_no_strengths_neutral(self) -> None:
        intent = build_intent(preferred_strengths=("code",))
        config = build_routing_config()
        provider = build_provider_config()

        with_strengths = score_candidate(
            "m", build_model_config(strengths=("code",), quality=0.5), provider, intent, config, 0.0
        )
        without = score_candidate(
            "m", build_model_config(strengths=(), quality=0.5), provider, intent, config, 0.0
        )
        # Neutral (no strengths) should score between match and mismatch
        assert with_strengths.score >= without.score
