"""Tests for negative signal suppression."""

from stronghold.classifier.keyword import score_keywords
from stronghold.types.config import TaskTypeConfig

TASK_TYPES = {
    "code": TaskTypeConfig(keywords=["code", "function", "bug"]),
    "chat": TaskTypeConfig(keywords=["hello", "hi"]),
}


class TestNegativeSignals:
    def test_what_is_the_penalizes_code(self) -> None:
        # "what is the" is a negative signal for code
        scores = score_keywords("what is the function of this organ", TASK_TYPES)
        # Should have negative pressure against code
        code_score = scores.get("code", 0)
        # "function" gives +1 but "what is the" gives -2 = net -1
        assert code_score <= 0
