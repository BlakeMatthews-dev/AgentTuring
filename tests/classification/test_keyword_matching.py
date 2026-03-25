"""Tests for keyword-based intent classification."""

from stronghold.classifier.keyword import score_keywords
from stronghold.types.config import TaskTypeConfig

TASK_TYPES = {
    "code": TaskTypeConfig(
        keywords=["code", "function", "bug", "error", "implement", "refactor"],
        min_tier="medium",
        preferred_strengths=["code"],
    ),
    "automation": TaskTypeConfig(
        keywords=["light", "fan", "turn on", "turn off", "chore"],
        min_tier="small",
        preferred_strengths=["chat"],
    ),
    "chat": TaskTypeConfig(
        keywords=["hello", "hi", "hey", "thanks"],
        min_tier="small",
        preferred_strengths=["chat"],
    ),
    "creative": TaskTypeConfig(
        keywords=["write", "story", "poem", "creative"],
        min_tier="small",
        preferred_strengths=["creative"],
    ),
}


class TestStrongIndicators:
    def test_strong_indicator_scores_three(self) -> None:
        scores = score_keywords("write a function to sort", TASK_TYPES)
        assert scores.get("code", 0) >= 3.0

    def test_turn_on_the_triggers_automation(self) -> None:
        scores = score_keywords("turn on the fan", TASK_TYPES)
        assert scores.get("automation", 0) >= 3.0


class TestConfigKeywords:
    def test_keyword_scores_one(self) -> None:
        scores = score_keywords("fix the bug", TASK_TYPES)
        assert scores.get("code", 0) >= 1.0

    def test_multiple_keywords_accumulate(self) -> None:
        scores = score_keywords("implement a function to fix the error", TASK_TYPES)
        assert scores.get("code", 0) >= 3.0


class TestDefaultToChat:
    def test_no_match_returns_empty_or_chat(self) -> None:
        scores = score_keywords("what is the meaning of life", TASK_TYPES)
        # Either empty scores or chat scores low
        code_score = scores.get("code", 0)
        assert code_score < 3.0


class TestWordBoundary:
    def test_return_on_investment_does_not_match_turn_on(self) -> None:
        scores = score_keywords("return on the investment", TASK_TYPES)
        # "turn on the" should NOT match inside "return on the"
        assert scores.get("automation", 0) < 3.0


class TestEdgeCases:
    def test_empty_text(self) -> None:
        scores = score_keywords("", TASK_TYPES)
        assert len(scores) == 0

    def test_only_whitespace(self) -> None:
        scores = score_keywords("   ", TASK_TYPES)
        assert len(scores) == 0

    def test_very_long_text(self) -> None:
        scores = score_keywords("code " * 500, TASK_TYPES)
        assert scores.get("code", 0) >= 1.0

    def test_case_insensitive(self) -> None:
        scores = score_keywords("WRITE A FUNCTION", TASK_TYPES)
        assert scores.get("code", 0) >= 3.0

    def test_multiple_strong_indicators_stack(self) -> None:
        scores = score_keywords("write a function and debug this", TASK_TYPES)
        assert scores.get("code", 0) >= 6.0

    def test_mixed_intents_both_score(self) -> None:
        scores = score_keywords("turn on the fan and write a function", TASK_TYPES)
        assert scores.get("automation", 0) > 0
        assert scores.get("code", 0) > 0

    def test_creative_keyword(self) -> None:
        scores = score_keywords("write a story about dragons", TASK_TYPES)
        assert scores.get("creative", 0) >= 3.0

    def test_greeting(self) -> None:
        scores = score_keywords("hello there how are you", TASK_TYPES)
        assert scores.get("chat", 0) >= 1.0


class TestNegativeInteraction:
    def test_negative_cancels_positive(self) -> None:
        scores = score_keywords("what is the meaning of code", TASK_TYPES)
        # "code" +1 keyword, "what is the" -2 = net -1 (not positive)
        code_score = scores.get("code", 0)
        assert code_score <= 0

    def test_strong_indicator_survives_negative(self) -> None:
        scores = score_keywords("what is the way to write a function", TASK_TYPES)
        # "write a function" +3, "what is the" -2 = net +1
        assert scores.get("code", 0) > 0
