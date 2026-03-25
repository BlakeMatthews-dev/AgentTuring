"""Tests for the full learning feedback loop: extraction, dedup, promotion, scoping."""

import pytest

from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.memory import Learning, MemoryScope
from tests.factories import build_learning


class TestCorrectionExtraction:
    """Fail-then-succeed patterns should produce learnings."""

    def test_fail_then_succeed_extracts_learning(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "wrong"},
                "result": "Error: entity not found",
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK turned on",
            },
        ]
        learnings = extractor.extract_corrections("turn on the bedroom fan", history)
        assert len(learnings) == 1
        assert learnings[0].category == "tool_correction"
        assert learnings[0].tool_name == "ha_control"
        assert len(learnings[0].trigger_keys) > 0

    def test_learning_has_correct_keys(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "bad"},
                "result": "Error: not found",
            },
            {"tool_name": "ha_control", "arguments": {"entity_id": "good"}, "result": "Success"},
        ]
        learnings = extractor.extract_corrections("turn on bedroom fan", history)
        assert len(learnings) == 1
        lr = learnings[0]
        assert lr.scope == MemoryScope.AGENT
        assert lr.source_query == "turn on bedroom fan"
        assert "ha_control" in lr.learning

    def test_no_extraction_when_all_succeed(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {"entity_id": "fan.ok"}, "result": "OK"},
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.ok2"},
                "result": "OK again",
            },
        ]
        learnings = extractor.extract_corrections("turn on the fan", history)
        assert len(learnings) == 0

    def test_no_extraction_when_all_fail(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "bad1"},
                "result": "Error: not found",
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "bad2"},
                "result": "Error: still not found",
            },
        ]
        learnings = extractor.extract_corrections("turn on the fan", history)
        assert len(learnings) == 0

    def test_no_extraction_single_call(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {"entity_id": "ok"}, "result": "Error: nope"},
        ]
        learnings = extractor.extract_corrections("turn on the fan", history)
        assert len(learnings) == 0

    def test_multiple_tools_independent_extraction(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {"e": "bad"}, "result": "Error: not found"},
            {"tool_name": "ha_control", "arguments": {"e": "good"}, "result": "OK"},
            {"tool_name": "web_search", "arguments": {"q": "wrong"}, "result": "Error: timeout"},
            {"tool_name": "web_search", "arguments": {"q": "right"}, "result": "Results found"},
        ]
        learnings = extractor.extract_corrections("search and turn on fan", history)
        assert len(learnings) == 2
        tool_names = {lr.tool_name for lr in learnings}
        assert "ha_control" in tool_names
        assert "web_search" in tool_names

    def test_fail_succeed_fail_extracts_first_correction(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {"e": "bad"}, "result": "Error: no"},
            {"tool_name": "ha_control", "arguments": {"e": "good"}, "result": "OK"},
            {"tool_name": "ha_control", "arguments": {"e": "bad2"}, "result": "Error: no again"},
        ]
        learnings = extractor.extract_corrections("do something", history)
        assert len(learnings) >= 1

    def test_trigger_keys_from_user_text(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {}, "result": "Error: fail"},
            {"tool_name": "ha_control", "arguments": {}, "result": "Success"},
        ]
        learnings = extractor.extract_corrections("turn on the bedroom fan please", history)
        assert len(learnings) == 1
        keys = learnings[0].trigger_keys
        assert all(len(k) > 2 for k in keys)
        assert len(keys) <= 5

    def test_long_user_text_truncated_in_source_query(self) -> None:
        extractor = ToolCorrectionExtractor()
        long_text = "x " * 100
        history = [
            {"tool_name": "t", "arguments": {}, "result": "Error: bad"},
            {"tool_name": "t", "arguments": {}, "result": "OK"},
        ]
        learnings = extractor.extract_corrections(long_text, history)
        assert len(learnings) == 1
        assert len(learnings[0].source_query) <= 80


class TestPositivePatternExtraction:
    """First-try successes on round 0 should be captured."""

    def test_round_zero_success_extracted(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.ok"},
                "result": "OK",
                "round": 0,
            },
        ]
        learnings = extractor.extract_positive_patterns("turn on the fan", history)
        assert len(learnings) == 1
        assert learnings[0].category == "positive_pattern"

    def test_round_one_success_not_extracted(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.ok"},
                "result": "OK",
                "round": 1,
            },
        ]
        learnings = extractor.extract_positive_patterns("turn on the fan", history)
        assert len(learnings) == 0

    def test_round_zero_failure_not_extracted(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {}, "result": "Error: failed", "round": 0},
        ]
        learnings = extractor.extract_positive_patterns("turn on the fan", history)
        assert len(learnings) == 0

    def test_multiple_round_zero_successes(self) -> None:
        extractor = ToolCorrectionExtractor()
        history = [
            {"tool_name": "ha_control", "arguments": {"a": 1}, "result": "OK", "round": 0},
            {"tool_name": "web_search", "arguments": {"q": "x"}, "result": "Found", "round": 0},
        ]
        learnings = extractor.extract_positive_patterns("search and control", history)
        assert len(learnings) == 2


class TestDedupOnStore:
    """Over 50% key overlap should update, not create."""

    @pytest.mark.asyncio
    async def test_high_overlap_updates_existing(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(trigger_keys=["fan", "bedroom", "light"], learning="version 1")
        l2 = build_learning(trigger_keys=["fan", "bedroom", "switch"], learning="version 2")
        id1 = await store.store(l1)
        id2 = await store.store(l2)
        assert id2 == id1  # updated, not new
        results = await store.find_relevant("fan bedroom", agent_id="warden-at-arms")
        assert len(results) == 1
        assert results[0].learning == "version 2"

    @pytest.mark.asyncio
    async def test_low_overlap_creates_new(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(trigger_keys=["fan", "bedroom"], learning="v1")
        l2 = build_learning(trigger_keys=["light", "kitchen", "switch"], learning="v2")
        id1 = await store.store(l1)
        id2 = await store.store(l2)
        assert id2 != id1

    @pytest.mark.asyncio
    async def test_dedup_requires_same_tool_name(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(trigger_keys=["fan", "bedroom"], tool_name="ha_control")
        l2 = build_learning(trigger_keys=["fan", "bedroom"], tool_name="web_search")
        await store.store(l1)
        await store.store(l2)
        # Different tools -> both stored
        all_results = await store.find_relevant("fan bedroom")
        assert len(all_results) == 2

    @pytest.mark.asyncio
    async def test_dedup_requires_same_agent_id(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(trigger_keys=["fan", "bedroom"], agent_id="agent-a")
        l2 = build_learning(trigger_keys=["fan", "bedroom"], agent_id="agent-b")
        await store.store(l1)
        await store.store(l2)
        results_a = await store.find_relevant("fan bedroom", agent_id="agent-a")
        results_b = await store.find_relevant("fan bedroom", agent_id="agent-b")
        assert len(results_a) == 1
        assert len(results_b) == 1


class TestAutoPromotion:
    """hit_count >= 5 should promote the learning."""

    @pytest.mark.asyncio
    async def test_hit_count_below_threshold_not_promoted(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        for _ in range(4):
            await store.mark_used([lid])
        promoted = await store.check_auto_promotions(threshold=5)
        assert len(promoted) == 0

    @pytest.mark.asyncio
    async def test_hit_count_at_threshold_promoted(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        for _ in range(5):
            await store.mark_used([lid])
        promoted = await store.check_auto_promotions(threshold=5)
        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    @pytest.mark.asyncio
    async def test_hit_count_above_threshold_promoted(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        for _ in range(10):
            await store.mark_used([lid])
        promoted = await store.check_auto_promotions(threshold=5)
        assert len(promoted) == 1

    @pytest.mark.asyncio
    async def test_already_promoted_not_re_promoted(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        for _ in range(5):
            await store.mark_used([lid])
        promoted1 = await store.check_auto_promotions(threshold=5)
        assert len(promoted1) == 1
        promoted2 = await store.check_auto_promotions(threshold=5)
        assert len(promoted2) == 0  # already promoted

    @pytest.mark.asyncio
    async def test_get_promoted_returns_promoted_only(self) -> None:
        store = InMemoryLearningStore()
        lid1 = await store.store(build_learning(trigger_keys=["fan"], agent_id="a1"))
        lid2 = await store.store(build_learning(trigger_keys=["light"], agent_id="a2"))
        for _ in range(5):
            await store.mark_used([lid1])
        await store.check_auto_promotions(threshold=5)
        promoted = await store.get_promoted()
        assert len(promoted) == 1
        assert promoted[0].id == lid1


class TestAgentScoping:
    """Learning from agent A should be invisible to agent B."""

    @pytest.mark.asyncio
    async def test_agent_a_invisible_to_agent_b(self) -> None:
        store = InMemoryLearningStore()
        await store.store(build_learning(agent_id="agent-a", trigger_keys=["secret"]))
        results = await store.find_relevant("secret", agent_id="agent-b")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_agent_sees_own_learnings(self) -> None:
        store = InMemoryLearningStore()
        await store.store(build_learning(agent_id="agent-a", trigger_keys=["mine"]))
        results = await store.find_relevant("mine", agent_id="agent-a")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_agent_filter_returns_all(self) -> None:
        store = InMemoryLearningStore()
        await store.store(build_learning(agent_id="agent-a", trigger_keys=["shared"]))
        await store.store(build_learning(agent_id="agent-b", trigger_keys=["shared"]))
        results = await store.find_relevant("shared")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_multiple_agents_isolated(self) -> None:
        store = InMemoryLearningStore()
        for i in range(5):
            await store.store(
                build_learning(
                    agent_id=f"agent-{i}",
                    trigger_keys=["common"],
                    learning=f"learning from agent {i}",
                )
            )
        for i in range(5):
            results = await store.find_relevant("common", agent_id=f"agent-{i}")
            assert len(results) == 1
            assert f"agent {i}" in results[0].learning
