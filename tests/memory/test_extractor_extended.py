"""Extended tests for ToolCorrectionExtractor and RCAExtractor.

Covers uncovered paths: positive patterns, RCA with LLM, RCA error handling,
multiple fail-succeed patterns, trigger key extraction.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.memory.learnings.extractor import RCAExtractor, ToolCorrectionExtractor
from tests.fakes import FakeLLMClient


# ---------------------------------------------------------------------------
# ToolCorrectionExtractor -- positive patterns
# ---------------------------------------------------------------------------


class TestPositivePatternExtended:
    def test_round_zero_success_creates_positive_pattern(self) -> None:
        """First-try success (round 0) on a successful result creates a positive_pattern."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "weather today"},
                "result": "Sunny, 72F",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("what is the weather today", tool_history)
        assert len(learnings) == 1
        assert learnings[0].category == "positive_pattern"
        assert "web_search" in learnings[0].learning
        assert learnings[0].tool_name == "web_search"
        assert learnings[0].source_query == "what is the weather today"

    def test_later_rounds_are_ignored(self) -> None:
        """Only round 0 entries produce positive patterns -- later rounds are skipped."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "q"},
                "result": "OK",
                "round": 1,
            },
            {
                "tool_name": "web_search",
                "arguments": {"query": "q2"},
                "result": "OK",
                "round": 2,
            },
        ]
        learnings = extractor.extract_positive_patterns("search something", tool_history)
        assert len(learnings) == 0

    def test_error_results_are_ignored(self) -> None:
        """Round 0 entries with error results do not produce positive patterns."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: entity not found",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("turn on fan", tool_history)
        assert len(learnings) == 0

    def test_error_in_lowercase_also_ignored(self) -> None:
        """Results containing 'error' (case-insensitive) are not positive."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "q"},
                "result": "There was an error in the request",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("search", tool_history)
        assert len(learnings) == 0

    def test_multiple_round_zero_successes(self) -> None:
        """Multiple tools succeeding on round 0 each produce a learning."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "q1"},
                "result": "Result 1",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "Turned on",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("search and turn on", tool_history)
        assert len(learnings) == 2
        tool_names = {l.tool_name for l in learnings}
        assert tool_names == {"web_search", "ha_control"}

    def test_trigger_keys_extracted(self) -> None:
        """Trigger keys are extracted from user text (words > 2 chars, max 5)."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "q"},
                "result": "OK",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns(
            "please search for the weather in portland",
            tool_history,
        )
        assert len(learnings) == 1
        keys = learnings[0].trigger_keys
        # "in" is only 2 chars, should be excluded
        assert "in" not in keys
        assert len(keys) <= 5
        assert all(len(k) > 2 for k in keys)


# ---------------------------------------------------------------------------
# ToolCorrectionExtractor -- corrections
# ---------------------------------------------------------------------------


class TestCorrectionExtended:
    def test_multiple_tools_with_corrections(self) -> None:
        """Multiple tools can each produce fail->succeed corrections."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 1,
            },
            {
                "tool_name": "web_search",
                "arguments": {"query": "bad query"},
                "result": "Error: no results",
                "round": 0,
            },
            {
                "tool_name": "web_search",
                "arguments": {"query": "good query"},
                "result": "Found results",
                "round": 1,
            },
        ]
        learnings = extractor.extract_corrections("turn on fan and search", tool_history)
        assert len(learnings) == 2
        tool_names = {l.tool_name for l in learnings}
        assert tool_names == {"ha_control", "web_search"}

    def test_trigger_keys_from_user_text(self) -> None:
        """Trigger keys are extracted from user text, limited to 5."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "bad"},
                "result": "Error: not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "good"},
                "result": "OK",
                "round": 1,
            },
        ]
        learnings = extractor.extract_corrections(
            "please turn on the bedroom ceiling fan right now",
            tool_history,
        )
        assert len(learnings) == 1
        keys = learnings[0].trigger_keys
        assert len(keys) <= 5
        assert all(len(k) > 2 for k in keys)
        # Short words like "on" and "the" should be excluded
        assert "on" not in keys

    def test_single_call_no_correction(self) -> None:
        """A tool called only once cannot form a fail->succeed pair."""
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "Error: not found",
                "round": 0,
            },
        ]
        learnings = extractor.extract_corrections("turn on fan", tool_history)
        assert len(learnings) == 0

    def test_empty_history(self) -> None:
        """Empty tool history produces no learnings."""
        extractor = ToolCorrectionExtractor()
        assert extractor.extract_corrections("something", []) == []
        assert extractor.extract_positive_patterns("something", []) == []

    def test_learning_scope_is_agent(self) -> None:
        """Corrections are scoped to AGENT level."""
        from stronghold.types.memory import MemoryScope

        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "bad"},
                "result": "Error: not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "good"},
                "result": "OK",
                "round": 1,
            },
        ]
        learnings = extractor.extract_corrections("turn on fan", tool_history)
        assert learnings[0].scope == MemoryScope.AGENT


# ---------------------------------------------------------------------------
# RCAExtractor
# ---------------------------------------------------------------------------


class TestRCAExtractor:
    async def test_rca_from_failures(self) -> None:
        """RCA is generated from failures using the LLM client."""
        llm = FakeLLMClient()
        llm.set_simple_response(
            "ROOT CAUSE: Wrong entity_id used\n"
            "PREVENTION: Look up entity IDs before calling ha_control"
        )
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: entity not found",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("turn on the fan", tool_history)
        assert learning is not None
        assert learning.category == "rca"
        assert "ROOT CAUSE" in learning.learning
        assert "ha_control" in learning.tool_name

    async def test_rca_returns_none_when_no_failures(self) -> None:
        """When all tool calls succeeded, RCA returns None."""
        llm = FakeLLMClient()
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "q"},
                "result": "Some successful result",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("search for things", tool_history)
        assert learning is None

    async def test_rca_returns_none_when_no_llm(self) -> None:
        """When no LLM client is provided, RCA returns None."""
        extractor = RCAExtractor(llm_client=None, rca_model="")
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {},
                "result": "Error: timeout",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("do something", tool_history)
        assert learning is None

    async def test_rca_handles_llm_errors(self) -> None:
        """When LLM call fails, RCA returns None gracefully."""
        llm = FakeLLMClient()
        # Set response with empty choices so content extraction returns ""
        llm.set_responses(
            {
                "id": "fake",
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
            }
        )
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {},
                "result": "Error: timeout",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("do something", tool_history)
        # Empty string from LLM -> None
        assert learning is None

    async def test_rca_failure_summary_includes_tool_details(self) -> None:
        """RCA prompt includes tool name, arguments, and error text."""
        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: Timeout\nPREVENTION: Retry")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "web_search",
                "arguments": {"query": "critical search"},
                "result": "Error: HTTP 500 Internal Server Error",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("search for critical data", tool_history)
        assert learning is not None
        # Verify the LLM was called with the right prompt
        assert len(llm.calls) == 1
        prompt_msg = llm.calls[0]["messages"][0]["content"]
        assert "web_search" in prompt_msg
        assert "critical search" in prompt_msg
        assert "HTTP 500" in prompt_msg

    async def test_rca_trigger_keys(self) -> None:
        """RCA learning has trigger keys from user text."""
        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: Bad input\nPREVENTION: Validate")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {},
                "result": "Error: fail",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("turn on the bedroom fan", tool_history)
        assert learning is not None
        assert len(learning.trigger_keys) <= 5
        assert all(len(k) > 2 for k in learning.trigger_keys)

    async def test_rca_multiple_failures(self) -> None:
        """RCA with multiple failures reports all of them."""
        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: Multiple failures\nPREVENTION: Fix all")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: not found",
                "round": 0,
            },
            {
                "tool_name": "web_search",
                "arguments": {"query": "bad"},
                "result": "Error: timeout",
                "round": 1,
            },
        ]
        learning = await extractor.extract_rca("do two things", tool_history)
        assert learning is not None
        # tool_name should contain both tools separated by |
        assert "ha_control" in learning.tool_name
        assert "web_search" in learning.tool_name

    async def test_rca_empty_history(self) -> None:
        """Empty tool history returns None."""
        llm = FakeLLMClient()
        extractor = RCAExtractor(llm_client=llm, rca_model="fast-model")
        learning = await extractor.extract_rca("something", [])
        assert learning is None

    async def test_rca_model_passed_to_llm(self) -> None:
        """The configured rca_model is passed to the LLM client."""
        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: x\nPREVENTION: y")
        extractor = RCAExtractor(llm_client=llm, rca_model="gpt-4o-mini")
        tool_history = [
            {
                "tool_name": "t",
                "arguments": {},
                "result": "Error: fail",
                "round": 0,
            },
        ]
        await extractor.extract_rca("test", tool_history)
        assert llm.calls[0]["model"] == "gpt-4o-mini"

    async def test_rca_scope_is_agent(self) -> None:
        """RCA learnings are scoped to AGENT level."""
        from stronghold.types.memory import MemoryScope

        llm = FakeLLMClient()
        llm.set_simple_response("ROOT CAUSE: x\nPREVENTION: y")
        extractor = RCAExtractor(llm_client=llm, rca_model="m")
        tool_history = [
            {
                "tool_name": "t",
                "arguments": {},
                "result": "Error: fail",
                "round": 0,
            },
        ]
        learning = await extractor.extract_rca("test", tool_history)
        assert learning is not None
        assert learning.scope == MemoryScope.AGENT
