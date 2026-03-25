"""Tests for learning extraction from tool histories."""

from stronghold.memory.learnings.extractor import ToolCorrectionExtractor


class TestCorrectionExtraction:
    def test_fail_then_succeed_produces_learning(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: entity not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 1,
            },
        ]
        learnings = extractor.extract_corrections("turn on the fan", tool_history)
        assert len(learnings) == 1
        assert "ha_control" in learnings[0].learning
        assert learnings[0].category == "tool_correction"

    def test_all_succeed_no_extraction(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 0,
            },
        ]
        learnings = extractor.extract_corrections("turn on the fan", tool_history)
        assert len(learnings) == 0

    def test_all_fail_no_extraction(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {},
                "result": "Error: missing args",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {},
                "result": "Error: still missing",
                "round": 1,
            },
        ]
        learnings = extractor.extract_corrections("turn on fan", tool_history)
        assert len(learnings) == 0


class TestPositiveExtraction:
    def test_first_try_success(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("turn on the fan", tool_history)
        assert len(learnings) == 1
        assert learnings[0].category == "positive_pattern"
