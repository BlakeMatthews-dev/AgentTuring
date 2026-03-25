"""Tests for smart home tier sizing."""

from stronghold.classifier.complexity import automation_min_tier


class TestSmartHomeTier:
    def test_short_command_stays_small(self) -> None:
        result = automation_min_tier("turn on fan", "small")
        assert result == "small"

    def test_long_command_bumps_to_medium(self) -> None:
        result = automation_min_tier(
            "turn on the bedroom fan and set brightness to fifty percent",
            "small",
        )
        assert result == "medium"

    def test_filler_words_stripped(self) -> None:
        # "please turn on the fan" — "please", "the" are filler
        # meaningful: "turn", "on", "fan" = 3 words = small
        result = automation_min_tier("please turn on the fan", "small")
        assert result == "small"
