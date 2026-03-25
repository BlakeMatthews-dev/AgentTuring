"""Tests for compound request detection."""

from stronghold.classifier.multi_intent import detect_multi_intent
from stronghold.types.config import TaskTypeConfig

TASK_TYPES = {
    "automation": TaskTypeConfig(keywords=["fan", "light", "turn on", "turn off"]),
    "search": TaskTypeConfig(keywords=["search", "weather", "look up"]),
    "code": TaskTypeConfig(keywords=["code", "function", "bug"]),
}


class TestMultiIntent:
    def test_detects_two_intents(self) -> None:
        result = detect_multi_intent(
            "turn on the fan and search for the weather",
            TASK_TYPES,
        )
        assert len(result) >= 2
        assert "automation" in result
        assert "search" in result

    def test_single_intent_returns_empty(self) -> None:
        result = detect_multi_intent("turn on the fan", TASK_TYPES)
        assert len(result) == 0

    def test_short_text_returns_empty(self) -> None:
        result = detect_multi_intent("hi", TASK_TYPES)
        assert len(result) == 0


class TestMultiIntentEdgeCases:
    def test_three_intents(self) -> None:
        result = detect_multi_intent(
            "turn on the fan and search for weather and write a function",
            TASK_TYPES,
        )
        assert len(result) >= 2

    def test_same_intent_repeated(self) -> None:
        result = detect_multi_intent(
            "turn on the fan and turn off the light",
            TASK_TYPES,
        )
        # Same intent (automation) twice — should not count as multi
        assert len(result) <= 1

    def test_does_not_split_on_and_in_normal_text(self) -> None:
        result = detect_multi_intent(
            "bread and butter",
            TASK_TYPES,
        )
        assert len(result) == 0
