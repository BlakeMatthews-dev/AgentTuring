"""Tests for learning auto-promotion."""

import pytest

from stronghold.memory.learnings.store import InMemoryLearningStore
from tests.factories import build_learning


class TestAutoPromotion:
    @pytest.mark.asyncio
    async def test_promotes_at_threshold(self) -> None:
        store = InMemoryLearningStore()
        learning = build_learning(trigger_keys=["test"])
        lid = await store.store(learning)

        # Hit it 5 times
        for _ in range(5):
            await store.mark_used([lid])

        promoted = await store.check_auto_promotions(threshold=5)
        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    @pytest.mark.asyncio
    async def test_does_not_promote_below_threshold(self) -> None:
        store = InMemoryLearningStore()
        learning = build_learning(trigger_keys=["test"])
        lid = await store.store(learning)
        await store.mark_used([lid])  # only 1 hit

        promoted = await store.check_auto_promotions(threshold=5)
        assert len(promoted) == 0

    @pytest.mark.asyncio
    async def test_get_promoted_returns_promoted(self) -> None:
        store = InMemoryLearningStore()
        learning = build_learning(trigger_keys=["test"])
        lid = await store.store(learning)
        for _ in range(5):
            await store.mark_used([lid])
        await store.check_auto_promotions(threshold=5)

        result = await store.get_promoted()
        assert len(result) == 1
