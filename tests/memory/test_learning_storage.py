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


class TestMarkOutcome:
    """Spec C: success/failure feedback via LearningStore.mark_outcome."""

    @pytest.mark.asyncio
    async def test_new_learning_has_zero_outcome_counts(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].id == lid
        assert results[0].success_after_use == 0
        assert results[0].failure_after_use == 0

    @pytest.mark.asyncio
    async def test_mark_success_increments_only_success(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        await store.mark_outcome([lid], success=True)
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].success_after_use == 1
        assert results[0].failure_after_use == 0

    @pytest.mark.asyncio
    async def test_mark_failure_increments_only_failure(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        await store.mark_outcome([lid], success=False)
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].success_after_use == 0
        assert results[0].failure_after_use == 1

    @pytest.mark.asyncio
    async def test_counts_are_monotonic(self) -> None:
        """Invariant: counts_monotonic — counts only go up, never down."""
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        for _ in range(3):
            await store.mark_outcome([lid], success=True)
        for _ in range(2):
            await store.mark_outcome([lid], success=False)
        # One more success must not reduce failure_after_use
        await store.mark_outcome([lid], success=True)
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].success_after_use == 4
        assert results[0].failure_after_use == 2

    @pytest.mark.asyncio
    async def test_multi_id_batch_all_incremented(self) -> None:
        """Invariant: outcome_counts_learning — every injected id gets +1."""
        store = InMemoryLearningStore()
        ids = [
            await store.store(build_learning(trigger_keys=[f"k{i}"], tool_name=f"t{i}"))
            for i in range(3)
        ]
        await store.mark_outcome(ids, success=True)
        for lid in ids:
            matches = [lr for lr in store._learnings if lr.id == lid]
            assert matches[0].success_after_use == 1

    @pytest.mark.asyncio
    async def test_empty_batch_is_noop(self) -> None:
        """Invariant: no_injection_no_change — empty list must mutate nothing."""
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        await store.mark_outcome([], success=True)
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        assert results[0].success_after_use == 0
        assert results[0].failure_after_use == 0

    @pytest.mark.asyncio
    async def test_unknown_ids_silently_ignored(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["fan"]))
        await store.mark_outcome([9999, lid], success=True)
        results = await store.find_relevant("fan", agent_id="warden-at-arms")
        # The real id is still incremented, unknowns are skipped without error
        assert results[0].success_after_use == 1

    @pytest.mark.asyncio
    async def test_cross_org_ids_silently_skipped(self) -> None:
        """Invariant: org_scoped — mark_outcome with an org_filter ignores other-org ids."""
        store = InMemoryLearningStore()
        lid_a = await store.store(
            build_learning(trigger_keys=["a"], org_id="org-a", tool_name="ta")
        )
        lid_b = await store.store(
            build_learning(trigger_keys=["b"], org_id="org-b", tool_name="tb")
        )
        # Caller in org-a tries to mark both; only its own should change
        await store.mark_outcome([lid_a, lid_b], success=True, org_id="org-a")
        a_match = [lr for lr in store._learnings if lr.id == lid_a][0]
        b_match = [lr for lr in store._learnings if lr.id == lid_b][0]
        assert a_match.success_after_use == 1
        assert b_match.success_after_use == 0


class TestListIneffective:
    """list_ineffective returns learnings that have been tried but mostly failed."""

    @pytest.mark.asyncio
    async def test_returns_learning_with_more_failures_than_successes(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["x"]))
        await store.mark_outcome([lid], success=False)
        await store.mark_outcome([lid], success=False)
        await store.mark_outcome([lid], success=True)
        # 2 failures vs 1 success; total uses = 3 >= min_uses 3
        results = await store.list_ineffective(min_uses=3)
        assert len(results) == 1
        assert results[0].id == lid

    @pytest.mark.asyncio
    async def test_excludes_learning_below_min_uses(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["x"]))
        await store.mark_outcome([lid], success=False)
        # Only 1 use, min_uses=5
        results = await store.list_ineffective(min_uses=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_excludes_mostly_successful_learning(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["x"]))
        for _ in range(4):
            await store.mark_outcome([lid], success=True)
        await store.mark_outcome([lid], success=False)
        # 4 success vs 1 failure — not ineffective
        results = await store.list_ineffective(min_uses=3)
        assert results == []

    @pytest.mark.asyncio
    async def test_excludes_untouched_learning(self) -> None:
        store = InMemoryLearningStore()
        await store.store(build_learning(trigger_keys=["x"]))
        results = await store.list_ineffective(min_uses=1)
        assert results == []

    @pytest.mark.asyncio
    async def test_tie_is_not_ineffective(self) -> None:
        """A tied success/failure count should NOT be flagged — only strictly worse."""
        store = InMemoryLearningStore()
        lid = await store.store(build_learning(trigger_keys=["x"]))
        await store.mark_outcome([lid], success=True)
        await store.mark_outcome([lid], success=False)
        results = await store.list_ineffective(min_uses=2)
        assert results == []
