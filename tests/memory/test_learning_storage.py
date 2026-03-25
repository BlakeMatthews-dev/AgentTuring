"""Tests for learning storage: CRUD, dedup, scoping."""

import pytest

from stronghold.memory.learnings.store import InMemoryLearningStore
from tests.factories import build_learning


class TestLearningStorage:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self) -> None:
        store = InMemoryLearningStore()
        learning = build_learning(trigger_keys=["fan", "bedroom"])
        lid = await store.store(learning)
        assert lid > 0

        results = await store.find_relevant("turn on the bedroom fan", agent_id="warden-at-arms")
        assert len(results) == 1
        assert "fan" in results[0].trigger_keys

    @pytest.mark.asyncio
    async def test_dedup_on_overlap(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(trigger_keys=["fan", "bedroom"], learning="v1")
        l2 = build_learning(trigger_keys=["fan", "bedroom", "light"], learning="v2")
        await store.store(l1)
        await store.store(l2)
        # Should have updated, not duplicated
        results = await store.find_relevant("fan bedroom", agent_id="warden-at-arms")
        assert len(results) == 1
        assert results[0].learning == "v2"

    @pytest.mark.asyncio
    async def test_agent_scoping(self) -> None:
        store = InMemoryLearningStore()
        l1 = build_learning(agent_id="agent-a", trigger_keys=["test"])
        l2 = build_learning(agent_id="agent-b", trigger_keys=["test"])
        await store.store(l1)
        await store.store(l2)

        results_a = await store.find_relevant("test", agent_id="agent-a")
        results_b = await store.find_relevant("test", agent_id="agent-b")
        assert len(results_a) == 1
        assert results_a[0].agent_id == "agent-a"
        assert len(results_b) == 1
        assert results_b[0].agent_id == "agent-b"


class TestLearningEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query_returns_nothing(self) -> None:
        store = InMemoryLearningStore()
        await store.store(build_learning(trigger_keys=["fan"]))
        results = await store.find_relevant("", agent_id="warden-at-arms")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_max_results_respected(self) -> None:
        store = InMemoryLearningStore()
        for i in range(20):
            await store.store(
                build_learning(
                    trigger_keys=["test"],
                    learning=f"learning {i}",
                    agent_id=f"a{i}",
                )
            )
        results = await store.find_relevant("test", max_results=5)
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_hit_count_increments(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        await store.mark_used([lid])
        await store.mark_used([lid])
        await store.mark_used([lid])
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].hit_count == 3
