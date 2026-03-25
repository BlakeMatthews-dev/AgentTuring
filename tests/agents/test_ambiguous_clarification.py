"""Test clarification when multiple intents score > 0 but < 3."""

import pytest

from stronghold.classifier.keyword import score_keywords
from stronghold.types.config import TaskTypeConfig


TASK_TYPES = {
    "code": TaskTypeConfig(keywords=["code", "function", "implement", "deploy"]),
    "chat": TaskTypeConfig(keywords=["hello", "hi", "help"]),
    "automation": TaskTypeConfig(keywords=["light", "fan", "turn on"]),
    "search": TaskTypeConfig(keywords=["search", "find", "look up"]),
}


class TestAmbiguousDetection:
    def test_zero_score_is_not_ambiguous(self) -> None:
        """Score 0 = general chat, not ambiguous."""
        scores = score_keywords("what is the meaning of life", TASK_TYPES)
        above_zero = {k: v for k, v in scores.items() if v > 0}
        # Either 0 or 1 intent matched — not ambiguous
        assert len(above_zero) <= 1

    def test_single_intent_above_zero_is_clear(self) -> None:
        """One intent > 0, rest 0 = clear intent, no clarification needed."""
        scores = score_keywords("hello there", TASK_TYPES)
        above_zero = {k: v for k, v in scores.items() if v > 0}
        assert len(above_zero) == 1
        assert "chat" in above_zero

    def test_two_intents_above_zero_is_ambiguous(self) -> None:
        """Two intents > 0 but < 3 = ambiguous, needs clarification."""
        scores = score_keywords("help me implement the deployment", TASK_TYPES)
        above_zero = {k: v for k, v in scores.items() if v > 0}
        # "help" → chat, "implement" + "deploy" → code
        # Both should be > 0
        assert len(above_zero) >= 2

    def test_strong_indicator_is_not_ambiguous(self) -> None:
        """Score >= 3 on one intent = confident, even if others > 0."""
        scores = score_keywords("write a function to help with sorting", TASK_TYPES)
        # "write a function" → code +3, "help" → chat +1
        max_score = max(scores.values()) if scores else 0
        assert max_score >= 3.0  # confident on code

    def test_ambiguous_helper(self) -> None:
        """Test the is_ambiguous helper."""
        from stronghold.classifier.engine import is_ambiguous

        # Clear: one strong signal
        assert not is_ambiguous({"code": 5.0, "chat": 0.0})
        # Clear: nothing matched
        assert not is_ambiguous({})
        # Clear: one weak signal
        assert not is_ambiguous({"chat": 1.0})
        # Ambiguous: two weak signals
        assert is_ambiguous({"code": 2.0, "chat": 1.0})
        # Ambiguous: three weak signals
        assert is_ambiguous({"code": 1.0, "chat": 1.0, "search": 1.0})
        # Not ambiguous: one strong dominates
        assert not is_ambiguous({"code": 5.0, "chat": 1.0})
