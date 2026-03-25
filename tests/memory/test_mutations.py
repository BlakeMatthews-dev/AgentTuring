"""Tests for in-memory skill mutation store."""

from __future__ import annotations

from stronghold.memory.mutations import InMemorySkillMutationStore
from stronghold.types.memory import SkillMutation


class TestInMemorySkillMutationStore:
    async def test_record_returns_id(self) -> None:
        store = InMemorySkillMutationStore()
        mutation = SkillMutation(skill_name="ha_control", learning_id=1)
        mid = await store.record(mutation)
        assert mid == 1

    async def test_record_increments_id(self) -> None:
        store = InMemorySkillMutationStore()
        m1 = await store.record(SkillMutation(skill_name="a"))
        m2 = await store.record(SkillMutation(skill_name="b"))
        assert m2 == m1 + 1

    async def test_list_mutations(self) -> None:
        store = InMemorySkillMutationStore()
        await store.record(SkillMutation(skill_name="a"))
        await store.record(SkillMutation(skill_name="b"))
        mutations = await store.list_mutations()
        assert len(mutations) == 2

    async def test_list_mutations_respects_limit(self) -> None:
        store = InMemorySkillMutationStore()
        for i in range(10):
            await store.record(SkillMutation(skill_name=f"skill-{i}"))
        mutations = await store.list_mutations(limit=3)
        assert len(mutations) == 3

    async def test_list_mutations_returns_most_recent(self) -> None:
        store = InMemorySkillMutationStore()
        for i in range(10):
            await store.record(SkillMutation(skill_name=f"skill-{i}"))
        mutations = await store.list_mutations(limit=2)
        assert mutations[-1].skill_name == "skill-9"

    async def test_empty_store_list(self) -> None:
        store = InMemorySkillMutationStore()
        mutations = await store.list_mutations()
        assert mutations == []

    async def test_mutation_id_set_on_object(self) -> None:
        store = InMemorySkillMutationStore()
        mutation = SkillMutation(skill_name="test")
        mid = await store.record(mutation)
        assert mutation.id == mid
