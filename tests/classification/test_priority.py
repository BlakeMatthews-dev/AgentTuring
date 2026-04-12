"""Tests for priority tier inference from urgency keywords."""

from stronghold.classifier.complexity import infer_priority


class TestPriorityKeywords:
    def test_emergency_is_p0(self) -> None:
        assert infer_priority("emergency the server is down") == "P0"

    def test_important_is_p1(self) -> None:
        assert infer_priority("this is important for the demo") == "P1"

    def test_fyi_is_p4(self) -> None:
        assert infer_priority("fyi here is the report") == "P4"

    def test_normal_text_is_p2(self) -> None:
        assert infer_priority("hello how are you") == "P2"
