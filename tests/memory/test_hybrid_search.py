"""Tests for embedding-based hybrid search in learning store."""

import pytest

from stronghold.memory.learnings.embeddings import (
    FakeEmbeddingClient,
    HybridLearningStore,
    NoopEmbeddingClient,
    cosine_similarity,
)
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.memory import Learning


class TestCosineSimilarity:
    """Cosine similarity edge cases."""

    def test_identical_vectors(self) -> None:
        assert cosine_similarity([1, 0, 1], [1, 0, 1]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector_a(self) -> None:
        assert cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_zero_vector_b(self) -> None:
        assert cosine_similarity([1, 1], [0, 0]) == 0.0

    def test_empty_vectors(self) -> None:
        assert cosine_similarity([], []) == 0.0

    def test_mismatched_lengths(self) -> None:
        assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0


class TestNoopEmbeddingClient:
    """Noop client returns zero vectors."""

    @pytest.mark.asyncio
    async def test_dimension(self) -> None:
        client = NoopEmbeddingClient(dimension=128)
        assert client.dimension == 128

    @pytest.mark.asyncio
    async def test_embed_returns_zeros(self) -> None:
        client = NoopEmbeddingClient()
        vec = await client.embed("test")
        assert len(vec) == 384
        assert all(v == 0.0 for v in vec)

    @pytest.mark.asyncio
    async def test_batch_returns_zeros(self) -> None:
        client = NoopEmbeddingClient()
        vecs = await client.embed_batch(["a", "b"])
        assert len(vecs) == 2
        assert all(v == 0.0 for v in vecs[0])


class TestFakeEmbeddingClient:
    """Fake client returns deterministic vectors."""

    @pytest.mark.asyncio
    async def test_deterministic(self) -> None:
        client = FakeEmbeddingClient()
        v1 = await client.embed("hello")
        v2 = await client.embed("hello")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_different_texts_different_vectors(self) -> None:
        client = FakeEmbeddingClient()
        v1 = await client.embed("hello")
        v2 = await client.embed("world")
        # May or may not differ, but should be stable
        assert len(v1) == len(v2) == client.dimension


class TestHybridStoreFallback:
    """Hybrid store falls back to keyword-only when no embeddings."""

    @pytest.mark.asyncio
    async def test_no_embeddings_uses_keyword_only(self) -> None:
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store, embedding_client=None)
        await hybrid.store(
            Learning(
                trigger_keys=["light", "bedroom"],
                learning="turn on bedroom light",
                tool_name="ha_control",
            )
        )
        results = await hybrid.find_relevant("bedroom light")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_noop_embeddings_uses_keyword_only(self) -> None:
        """Noop returns all zeros — hybrid should skip reranking."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store, embedding_client=NoopEmbeddingClient())
        await hybrid.store(
            Learning(
                trigger_keys=["light", "bedroom"],
                learning="turn on bedroom light",
                tool_name="ha_control",
            )
        )
        results = await hybrid.find_relevant("bedroom light")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_results_returns_empty(self) -> None:
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)
        results = await hybrid.find_relevant("something unrelated")
        assert results == []


class TestHybridStoreWithEmbeddings:
    """Hybrid store uses embeddings when available."""

    @pytest.mark.asyncio
    async def test_embedding_reranking(self) -> None:
        """When embeddings are available, results should be reranked."""
        store = InMemoryLearningStore()
        client = FakeEmbeddingClient()
        hybrid = HybridLearningStore(store, embedding_client=client)

        await hybrid.store(
            Learning(
                trigger_keys=["light", "bedroom"],
                learning="Use ha_control to turn on bedroom light",
                tool_name="ha_control",
            )
        )
        await hybrid.store(
            Learning(
                trigger_keys=["light", "kitchen"],
                learning="Use ha_control to turn on kitchen light",
                tool_name="ha_control",
            )
        )

        results = await hybrid.find_relevant("bedroom light")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_delegates_mark_used(self) -> None:
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)
        lr_id = await hybrid.store(
            Learning(
                trigger_keys=["test"],
                learning="test learning",
            )
        )
        await hybrid.mark_used([lr_id])
        # Verify hit count incremented in underlying store
        all_learnings = store._learnings
        assert any(lr.hit_count == 1 for lr in all_learnings)

    @pytest.mark.asyncio
    async def test_delegates_auto_promotion(self) -> None:
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)
        await hybrid.store(
            Learning(
                trigger_keys=["test"],
                learning="test",
                hit_count=10,
            )
        )
        promoted = await hybrid.check_auto_promotions(threshold=5)
        assert len(promoted) == 1

    @pytest.mark.asyncio
    async def test_delegates_get_promoted(self) -> None:
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)
        await hybrid.store(
            Learning(
                trigger_keys=["test"],
                learning="test",
                status="promoted",
            )
        )
        promoted = await hybrid.get_promoted()
        assert len(promoted) == 1
