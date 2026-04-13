"""Targeted coverage tests for memory modules.

Covers missed lines in:
- episodic/retrieval.py (line 114 = keyword_similarity edge case with empty sets)
- episodic/store.py (lines 99-104 = reinforce path)
- learnings/embeddings.py (lines 150-157 = embed uncached learning in find_relevant)
- outcomes.py (lines 119-127 = list_outcomes path)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stronghold.memory.episodic.retrieval import ScoredEpisodicRetrieval
from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.memory.learnings.embeddings import (
    FakeEmbeddingClient,
    HybridLearningStore,
)
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.types.memory import (
    EpisodicMemory,
    Learning,
    MemoryScope,
    MemoryTier,
    Outcome,
)


# ---------------------------------------------------------------------------
# Episodic retrieval: keyword_similarity edge case (retrieval.py line 114)
# ---------------------------------------------------------------------------


class TestEpisodicRetrievalEdgeCases:
    """Test edge cases in ScoredEpisodicRetrieval."""

    async def test_keyword_similarity_empty_query(self) -> None:
        """_keyword_similarity returns 0.0 when query_words is empty."""
        result = ScoredEpisodicRetrieval._keyword_similarity(set(), "some content")
        assert result == 0.0

    async def test_keyword_similarity_empty_content(self) -> None:
        """_keyword_similarity returns 0.0 when content is empty."""
        result = ScoredEpisodicRetrieval._keyword_similarity({"word"}, "")
        assert result == 0.0

    async def test_keyword_similarity_both_empty(self) -> None:
        """_keyword_similarity returns 0.0 when both are empty."""
        result = ScoredEpisodicRetrieval._keyword_similarity(set(), "")
        assert result == 0.0

    async def test_retrieve_no_scoped_memories_returns_empty(self) -> None:
        """When no memories match scope filters, return empty list."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="m1",
                content="test memory",
                scope=MemoryScope.ORGANIZATION,
                org_id="org-other",
                weight=0.5,
            )
        )
        retrieval = ScoredEpisodicRetrieval(store)
        results = await retrieval.retrieve("test", org_id="org-mine")
        assert results == []

    async def test_retrieve_with_embedding_fallback_on_failure(self) -> None:
        """When embedding fails for a specific memory, fall back to keyword."""

        class FailOnSecondEmbed:
            """Embedding client that fails on the second call."""

            def __init__(self) -> None:
                self._call_count = 0

            @property
            def dimension(self) -> int:
                return 4

            async def embed(self, text: str) -> list[float]:
                self._call_count += 1
                if self._call_count == 1:
                    # Return a real vector for the query
                    return [1.0, 0.5, 0.3, 0.1]
                # Fail for the memory embedding
                msg = "embedding failed"
                raise RuntimeError(msg)

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]

        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="m1",
                content="relevant test data",
                scope=MemoryScope.GLOBAL,
                weight=0.5,
            )
        )
        retrieval = ScoredEpisodicRetrieval(store, embedding_client=FailOnSecondEmbed())
        # Should not crash; falls back to keyword similarity for that memory
        # H17: org context required for GLOBAL-scoped memories
        results = await retrieval.retrieve("relevant test", org_id="org-test")
        # The memory should still be found via keyword fallback
        assert len(results) == 1
        assert results[0].memory_id == "m1"

    async def test_retrieve_skips_zero_score_memories(self) -> None:
        """Memories with zero overlap should not appear in results."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="m1",
                content="completely unrelated xyz",
                scope=MemoryScope.GLOBAL,
                weight=0.5,
            )
        )
        retrieval = ScoredEpisodicRetrieval(store)
        results = await retrieval.retrieve("nothing matching here", org_id="org-test")
        assert isinstance(results, list)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Episodic store: reinforce path (store.py lines 99-104)
# ---------------------------------------------------------------------------


class TestEpisodicStoreReinforce:
    """Test the reinforce method of InMemoryEpisodicStore."""

    async def test_reinforce_existing_memory(self) -> None:
        """Reinforcing a memory should increase its weight."""
        store = InMemoryEpisodicStore()
        mem = EpisodicMemory(
            memory_id="m1",
            tier=MemoryTier.LESSON,
            content="important lesson",
            weight=0.5,
            scope=MemoryScope.GLOBAL,
        )
        await store.store(mem)

        await store.reinforce("m1", delta=0.1)

        # The memory should now have a higher weight
        assert store._memories[0].weight == 0.6
        assert store._memories[0].reinforcement_count == 1

    async def test_reinforce_nonexistent_memory_is_noop(self) -> None:
        """Reinforcing a non-existent memory_id should not crash."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="m1",
                content="test",
                weight=0.5,
                scope=MemoryScope.GLOBAL,
            )
        )
        # Reinforce a non-existent ID — should not raise
        await store.reinforce("nonexistent", delta=0.1)
        # Original memory should be unchanged
        assert store._memories[0].weight == 0.5

    async def test_reinforce_clamps_to_tier_ceiling(self) -> None:
        """Reinforcing should not exceed the tier's weight ceiling."""
        store = InMemoryEpisodicStore()
        mem = EpisodicMemory(
            memory_id="m1",
            tier=MemoryTier.OBSERVATION,  # ceiling = 0.5
            content="observed thing",
            weight=0.5,
            scope=MemoryScope.GLOBAL,
        )
        await store.store(mem)

        await store.reinforce("m1", delta=0.2)

        # Should be clamped to 0.5 (OBSERVATION ceiling)
        assert store._memories[0].weight == 0.5


# ---------------------------------------------------------------------------
# HybridLearningStore: uncached embedding in find_relevant (embeddings.py 150-157)
# ---------------------------------------------------------------------------


class TestHybridLearningStoreEmbeddings:
    """Test the embedding path in HybridLearningStore.find_relevant()
    where learnings are not in the cache and must be embedded on the fly."""

    async def test_find_relevant_embeds_uncached_learnings(self) -> None:
        """Learnings not in the embedding cache should be embedded during search."""
        base_store = InMemoryLearningStore()
        embedding_client = FakeEmbeddingClient(dimension=8)
        hybrid = HybridLearningStore(base_store, embedding_client)

        # Store a learning directly in the base store (bypassing HybridLearningStore.store)
        # so it won't be in the embedding cache
        learning = Learning(
            trigger_keys=["error", "timeout"],
            learning="Retry with exponential backoff on timeout errors",
            tool_name="api_call",
            agent_id="agent1",
        )
        learning_id = await base_store.store(learning)

        # Confirm it's not in the cache
        assert learning_id not in hybrid._embedding_cache

        # Search for it — this should trigger on-the-fly embedding
        results = await hybrid.find_relevant("timeout error handling", agent_id="agent1")

        # The learning should be found and its embedding should now be cached
        assert len(results) >= 1
        assert any(r.learning == "Retry with exponential backoff on timeout errors" for r in results)
        assert learning_id in hybrid._embedding_cache

    async def test_find_relevant_handles_embed_failure_for_learning(self) -> None:
        """When embedding an individual learning fails, it should still appear
        with keyword-only scoring."""

        class FailOnNonQueryEmbed:
            """Embedding client that fails on non-query embeds."""

            def __init__(self) -> None:
                self._call_count = 0

            @property
            def dimension(self) -> int:
                return 4

            async def embed(self, text: str) -> list[float]:
                self._call_count += 1
                if self._call_count == 1:
                    # First call is the query embedding — return real vector
                    return [1.0, 0.5, 0.3, 0.1]
                # All subsequent calls (learning embeds) fail
                msg = "embedding service down"
                raise RuntimeError(msg)

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]

        base_store = InMemoryLearningStore()
        hybrid = HybridLearningStore(base_store, FailOnNonQueryEmbed())

        learning = Learning(
            trigger_keys=["deploy", "failure"],
            learning="Check pod health before deploy",
            tool_name="deploy_tool",
            agent_id="agent1",
        )
        await base_store.store(learning)

        # Should not crash — the learning embed failure is caught
        results = await hybrid.find_relevant("deploy failure", agent_id="agent1")
        # The learning should still be found via keyword scoring
        # (combined score = kw_score * 1.0 + 0.0 * 3.0 = kw_score)
        # kw_score for rank 0 of 1 item = 1.0, so combined = 1.0 >= 0.3
        assert len(results) >= 1
        assert any(r.learning == "Check pod health before deploy" for r in results)

    async def test_store_caches_embedding(self) -> None:
        """Storing via HybridLearningStore should cache the embedding."""
        base_store = InMemoryLearningStore()
        embedding_client = FakeEmbeddingClient(dimension=8)
        hybrid = HybridLearningStore(base_store, embedding_client)

        learning = Learning(
            trigger_keys=["cache", "test"],
            learning="Test caching behavior",
            tool_name="test_tool",
        )
        lid = await hybrid.store(learning)

        assert lid in hybrid._embedding_cache
        assert len(hybrid._embedding_cache[lid]) == 8

    async def test_store_without_embedding_client(self) -> None:
        """Storing without an embedding client should not cache."""
        base_store = InMemoryLearningStore()
        hybrid = HybridLearningStore(base_store, None)

        learning = Learning(
            trigger_keys=["no", "embeddings"],
            learning="No embedding client",
            tool_name="test_tool",
        )
        lid = await hybrid.store(learning)

        assert lid not in hybrid._embedding_cache

    async def test_find_relevant_with_learning_id_none(self) -> None:
        """Learning with id=None should still be embeddable during search."""
        base_store = InMemoryLearningStore()
        embedding_client = FakeEmbeddingClient(dimension=8)
        hybrid = HybridLearningStore(base_store, embedding_client)

        # Directly manipulate the base store to have a learning with id set
        # but not in the cache, so the embed path fires and caches it.
        learning = Learning(
            trigger_keys=["test", "edge"],
            learning="Edge case learning",
            tool_name="tool",
            agent_id="agent1",
        )
        await base_store.store(learning)  # This sets learning.id

        results = await hybrid.find_relevant("test edge case", agent_id="agent1")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Outcomes: list_outcomes (outcomes.py lines 119-127)
# ---------------------------------------------------------------------------


class TestOutcomesListOutcomes:
    """Test the list_outcomes method of InMemoryOutcomeStore."""

    async def test_list_outcomes_returns_recent(self) -> None:
        """list_outcomes should return outcomes within the time window."""
        store = InMemoryOutcomeStore()

        now = datetime.now(UTC)
        # Record some outcomes
        for i in range(5):
            await store.record(
                Outcome(
                    request_id=f"req-{i}",
                    task_type="code",
                    model_used="model-a",
                    success=i % 2 == 0,
                    created_at=now - timedelta(hours=i),
                )
            )

        results = await store.list_outcomes(days=7)
        assert len(results) == 5

    async def test_list_outcomes_filters_by_task_type(self) -> None:
        """list_outcomes with task_type filter should only return matching."""
        store = InMemoryOutcomeStore()

        await store.record(Outcome(task_type="code", model_used="m1", success=True))
        await store.record(Outcome(task_type="chat", model_used="m1", success=True))
        await store.record(Outcome(task_type="code", model_used="m2", success=False))

        results = await store.list_outcomes(task_type="code")
        assert len(results) == 2
        assert all(o.task_type == "code" for o in results)

    async def test_list_outcomes_respects_limit(self) -> None:
        """list_outcomes should respect the limit parameter."""
        store = InMemoryOutcomeStore()

        for i in range(10):
            await store.record(
                Outcome(task_type="code", model_used="m1", success=True)
            )

        results = await store.list_outcomes(limit=3)
        assert len(results) == 3

    async def test_list_outcomes_org_scoped(self) -> None:
        """list_outcomes should respect org_id scoping."""
        store = InMemoryOutcomeStore()

        await store.record(
            Outcome(task_type="code", model_used="m1", org_id="org-a")
        )
        await store.record(
            Outcome(task_type="code", model_used="m1", org_id="org-b")
        )
        await store.record(
            Outcome(task_type="code", model_used="m1", org_id="org-a")
        )

        results = await store.list_outcomes(org_id="org-a")
        assert len(results) == 2
        assert all(o.org_id == "org-a" for o in results)

    async def test_list_outcomes_excludes_old(self) -> None:
        """list_outcomes should exclude outcomes older than the time window."""
        store = InMemoryOutcomeStore()

        old = datetime.now(UTC) - timedelta(days=30)
        recent = datetime.now(UTC) - timedelta(hours=1)

        await store.record(
            Outcome(task_type="code", model_used="m1", created_at=old, request_id="old-req")
        )
        await store.record(
            Outcome(task_type="code", model_used="m1", created_at=recent, request_id="recent-req")
        )

        results = await store.list_outcomes(days=7)
        assert len(results) == 1
        assert results[0].request_id == "recent-req"

    async def test_list_outcomes_empty_store(self) -> None:
        """list_outcomes on empty store returns empty list."""
        store = InMemoryOutcomeStore()
        results = await store.list_outcomes()
        assert results == []

    async def test_list_outcomes_system_caller_only_sees_unscoped(self) -> None:
        """System caller (no org_id) should only see records without org_id."""
        store = InMemoryOutcomeStore()

        await store.record(
            Outcome(task_type="code", model_used="m1", org_id="org-a")
        )
        await store.record(
            Outcome(task_type="code", model_used="m1", org_id="")
        )

        # System caller: org_id="" => only see unscoped records
        results = await store.list_outcomes(org_id="")
        assert len(results) == 1
        assert results[0].org_id == ""
