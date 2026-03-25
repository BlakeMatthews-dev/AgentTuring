"""Tests for scored episodic retrieval with scope filtering."""

import pytest

from stronghold.memory.episodic.retrieval import ScoredEpisodicRetrieval
from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.memory.learnings.embeddings import NoopEmbeddingClient
from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier


def _make_memory(
    content: str,
    *,
    scope: MemoryScope = MemoryScope.GLOBAL,
    weight: float = 0.5,
    tier: MemoryTier = MemoryTier.LESSON,
    agent_id: str | None = None,
    user_id: str | None = None,
    team_id: str = "",
    org_id: str = "",
) -> EpisodicMemory:
    return EpisodicMemory(
        content=content,
        scope=scope,
        weight=weight,
        tier=tier,
        org_id=org_id,
        team_id=team_id,
        agent_id=agent_id,
        user_id=user_id,
    )


class TestBasicRetrieval:
    """Basic retrieval with keyword scoring."""

    @pytest.mark.asyncio
    async def test_finds_matching_memory(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_make_memory("Python is a great programming language"))
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python programming")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_make_memory("Python programming"))
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("completely unrelated query")
        assert results == []

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        store = InMemoryEpisodicStore()
        for i in range(10):
            await store.store(_make_memory(f"memory about topic {i} with python"))
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python topic", limit=3)
        assert len(results) <= 3


class TestWeightBasedRanking:
    """Higher weight memories should rank above lower weight ones."""

    @pytest.mark.asyncio
    async def test_higher_weight_ranks_first(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "python is useful",
                weight=0.3,
                tier=MemoryTier.OBSERVATION,
            )
        )
        await store.store(
            _make_memory(
                "python is powerful",
                weight=0.9,
                tier=MemoryTier.WISDOM,
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python")
        assert len(results) == 2
        # Higher weight should be first
        assert results[0].weight >= results[1].weight


class TestOrgScopeIsolation:
    """Memories from different orgs must not leak."""

    @pytest.mark.asyncio
    async def test_org_scoped_visible_to_same_org(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "org secret info about python",
                scope=MemoryScope.ORGANIZATION,
                org_id="org-1",
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python", org_id="org-1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_org_scoped_invisible_to_other_org(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "org secret info about python",
                scope=MemoryScope.ORGANIZATION,
                org_id="org-1",
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python", org_id="org-2")
        assert results == []

    @pytest.mark.asyncio
    async def test_global_visible_to_all_orgs(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "global knowledge about python",
                scope=MemoryScope.GLOBAL,
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        r1 = await retriever.retrieve("python", org_id="org-1")
        r2 = await retriever.retrieve("python", org_id="org-2")
        assert len(r1) == 1
        assert len(r2) == 1


class TestTeamScopeIsolation:
    """Team-scoped memories visible within team only, org-enforced."""

    @pytest.mark.asyncio
    async def test_team_scoped_visible_to_same_team(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "team alpha knowledge about python",
                scope=MemoryScope.TEAM,
                team_id="team-alpha",
                org_id="org-1",
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python", team_id="team-alpha", org_id="org-1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_team_scoped_invisible_to_other_team(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "team alpha knowledge about python",
                scope=MemoryScope.TEAM,
                team_id="team-alpha",
                org_id="org-1",
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python", team_id="team-beta", org_id="org-1")
        assert results == []

    @pytest.mark.asyncio
    async def test_same_team_name_different_org_no_leakage(self) -> None:
        """CRITICAL: team 'alpha' in org-1 must not leak to team 'alpha' in org-2."""
        store = InMemoryEpisodicStore()
        await store.store(
            _make_memory(
                "org-1 secret about python",
                scope=MemoryScope.TEAM,
                team_id="team-alpha",
                org_id="org-1",
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        # org-2 querying for same team name should get nothing
        results = await retriever.retrieve("python", team_id="team-alpha", org_id="org-2")
        assert results == [], "Cross-org team leakage detected!"


class TestEmbeddingRetrieval:
    """Retrieval with embedding client (noop should fall back to keyword)."""

    @pytest.mark.asyncio
    async def test_noop_embedding_falls_back(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(_make_memory("python programming language"))
        retriever = ScoredEpisodicRetrieval(store, embedding_client=NoopEmbeddingClient())
        results = await retriever.retrieve("python programming")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_deleted_memories_excluded(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                content="deleted memory about python",
                deleted=True,
                scope=MemoryScope.GLOBAL,
                weight=0.5,
            )
        )
        retriever = ScoredEpisodicRetrieval(store)
        results = await retriever.retrieve("python")
        assert results == []
