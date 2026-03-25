"""Tests for learning auto-promotion logic (LearningPromoter)."""

from __future__ import annotations

from typing import Any

from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.mutations import InMemorySkillMutationStore
from stronghold.types.memory import Learning
from tests.factories import build_learning


class TestLearningPromoter:
    async def test_no_promotions_when_below_threshold(self) -> None:
        store = InMemoryLearningStore()
        lr = build_learning(hit_count=2)
        await store.store(lr)
        promoter = LearningPromoter(store, threshold=5)
        promoted = await promoter.check_and_promote()
        assert promoted == []

    async def test_promotes_when_threshold_reached(self) -> None:
        store = InMemoryLearningStore()
        lr = build_learning(hit_count=5)
        await store.store(lr)
        promoter = LearningPromoter(store, threshold=5)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    async def test_promoted_learning_has_correct_tool_name(self) -> None:
        store = InMemoryLearningStore()
        lr = build_learning(hit_count=10, tool_name="ha_control")
        await store.store(lr)
        promoter = LearningPromoter(store, threshold=5)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        assert promoted[0].tool_name == "ha_control"

    async def test_skill_mutation_triggered(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()

        class FakeForge:
            async def mutate(
                self, tool_name: str, learning: Learning,
            ) -> dict[str, Any]:
                return {"status": "mutated", "old_hash": "aaa", "new_hash": "bbb"}

        lr = build_learning(hit_count=10, tool_name="ha_control")
        await store.store(lr)
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=FakeForge(),
            mutation_store=mutation_store,
        )
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        # Mutation should have been recorded
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 1
        assert mutations[0].skill_name == "ha_control"

    async def test_mutation_error_handled(self) -> None:
        store = InMemoryLearningStore()

        class FailingForge:
            async def mutate(
                self, tool_name: str, learning: Learning,
            ) -> dict[str, Any]:
                return {"status": "error", "error": "forge failed"}

        lr = build_learning(hit_count=10, tool_name="ha_control")
        await store.store(lr)
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=FailingForge(),
        )
        # Should not raise
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1

    async def test_mutation_exception_handled(self) -> None:
        store = InMemoryLearningStore()

        class ExplodingForge:
            async def mutate(
                self, tool_name: str, learning: Learning,
            ) -> dict[str, Any]:
                raise RuntimeError("kaboom")

        lr = build_learning(hit_count=10, tool_name="ha_control")
        await store.store(lr)
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=ExplodingForge(),
        )
        # Should not raise
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1

    async def test_no_mutation_without_forge(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        lr = build_learning(hit_count=10, tool_name="ha_control")
        await store.store(lr)
        promoter = LearningPromoter(
            store,
            threshold=5,
            mutation_store=mutation_store,
        )
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0

    async def test_no_mutation_without_tool_name(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()

        class FakeForge:
            mutate_called = False

            async def mutate(
                self, tool_name: str, learning: Learning,
            ) -> dict[str, Any]:
                self.mutate_called = True
                return {"status": "mutated", "old_hash": "a", "new_hash": "b"}

        forge = FakeForge()
        lr = build_learning(hit_count=10, tool_name="")
        await store.store(lr)
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
        )
        await promoter.check_and_promote()
        assert not forge.mutate_called
