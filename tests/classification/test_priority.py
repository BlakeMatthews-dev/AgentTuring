"""Tests for priority inference from urgency keywords."""

from stronghold.classifier.complexity import infer_priority


class TestPriorityKeywords:
    def test_emergency_is_critical(self) -> None:
        assert infer_priority("emergency the server is down") == "critical"

    def test_important_is_high(self) -> None:
        assert infer_priority("this is important for the demo") == "high"

    def test_fyi_is_low(self) -> None:
        assert infer_priority("fyi here is the report") == "low"

    def test_normal_text_is_normal(self) -> None:
        assert infer_priority("hello how are you") == "normal"
