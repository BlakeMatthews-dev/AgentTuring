"""Tests for cross-tenant data leak fixes H14-H17.

H14: HybridLearningStore.find_relevant() drops org_id -> tenant A sees tenant B learnings.
H15: HybridLearningStore.check_auto_promotions() / get_promoted() drop org_id.
H16: EpisodicStore protocol uses `team` but impl uses `team_id` -> arg silently dropped.
H17: _matches_scope() returns GLOBAL memories when caller_org is empty even if memory has org_id.
"""

import pytest

from stronghold.memory.episodic.store import InMemoryEpisodicStore, _matches_scope
from stronghold.memory.learnings.embeddings import (
    FakeEmbeddingClient,
    HybridLearningStore,
)
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.memory import EpisodicMemory, Learning, MemoryScope, MemoryTier


# ---------------------------------------------------------------------------
# H14: HybridLearningStore.find_relevant must forward org_id
# ---------------------------------------------------------------------------
class TestH14HybridFindRelevantOrgIsolation:
    """find_relevant() on HybridLearningStore must respect org_id."""

    @pytest.mark.asyncio
    async def test_find_relevant_forwards_org_id(self) -> None:
        """Learnings from org-A must be invisible to org-B through the hybrid wrapper."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store, embedding_client=FakeEmbeddingClient())

        await hybrid.store(
            Learning(
                trigger_keys=["deploy", "kubernetes"],
                learning="use rolling update for k8s deploys",
                tool_name="kubectl",
                org_id="org-alpha",
            )
        )
        await hybrid.store(
            Learning(
                trigger_keys=["deploy", "kubernetes"],
                learning="use blue-green for k8s deploys",
                tool_name="kubectl",
                org_id="org-beta",
            )
        )

        results_alpha = await hybrid.find_relevant("kubernetes deploy", org_id="org-alpha")
        results_beta = await hybrid.find_relevant("kubernetes deploy", org_id="org-beta")

        # Each org must see ONLY its own learning
        assert len(results_alpha) == 1
        assert results_alpha[0].org_id == "org-alpha"
        assert len(results_beta) == 1
        assert results_beta[0].org_id == "org-beta"

    @pytest.mark.asyncio
    async def test_find_relevant_without_org_excludes_org_scoped(self) -> None:
        """System caller (no org_id) must not see org-scoped learnings."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)

        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="org-specific deploy tip",
                tool_name="kubectl",
                org_id="org-alpha",
            )
        )

        results = await hybrid.find_relevant("deploy")
        assert results == []

    @pytest.mark.asyncio
    async def test_find_relevant_no_embeddings_still_org_scoped(self) -> None:
        """Even the keyword-only fallback path must filter by org_id."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store, embedding_client=None)

        await hybrid.store(
            Learning(
                trigger_keys=["test"],
                learning="org-alpha test pattern",
                tool_name="tester",
                org_id="org-alpha",
            )
        )

        results = await hybrid.find_relevant("test", org_id="org-beta")
        assert results == []


# ---------------------------------------------------------------------------
# H15: HybridLearningStore.check_auto_promotions / get_promoted must forward org_id
# ---------------------------------------------------------------------------
class TestH15HybridPromotionOrgIsolation:
    """check_auto_promotions() and get_promoted() must respect org_id."""

    @pytest.mark.asyncio
    async def test_check_auto_promotions_org_scoped(self) -> None:
        """Only learnings within the caller's org should be promoted."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)

        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="alpha deploy tip",
                tool_name="kubectl",
                org_id="org-alpha",
                hit_count=10,
            )
        )
        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="beta deploy tip",
                tool_name="kubectl",
                org_id="org-beta",
                hit_count=10,
            )
        )

        promoted = await hybrid.check_auto_promotions(threshold=5, org_id="org-alpha")
        assert len(promoted) == 1
        assert promoted[0].org_id == "org-alpha"

    @pytest.mark.asyncio
    async def test_get_promoted_org_scoped(self) -> None:
        """get_promoted() must only return promotions within caller's org."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)

        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="alpha promoted",
                tool_name="kubectl",
                org_id="org-alpha",
                status="promoted",
            )
        )
        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="beta promoted",
                tool_name="kubectl",
                org_id="org-beta",
                status="promoted",
            )
        )

        results = await hybrid.get_promoted(org_id="org-alpha")
        assert len(results) == 1
        assert results[0].org_id == "org-alpha"

    @pytest.mark.asyncio
    async def test_get_promoted_system_caller_excludes_org_scoped(self) -> None:
        """System caller (no org_id) must not see org-scoped promoted learnings."""
        store = InMemoryLearningStore()
        hybrid = HybridLearningStore(store)

        await hybrid.store(
            Learning(
                trigger_keys=["deploy"],
                learning="org-scoped promoted",
                tool_name="kubectl",
                org_id="org-alpha",
                status="promoted",
            )
        )

        results = await hybrid.get_promoted()
        assert results == []


# ---------------------------------------------------------------------------
# H16: EpisodicStore protocol uses `team` but impl uses `team_id`
# ---------------------------------------------------------------------------
class TestH16EpisodicProtocolTeamAlignment:
    """Protocol and impl must both use `team_id`, not `team`."""

    @pytest.mark.asyncio
    async def test_retrieve_with_team_id_kwarg(self) -> None:
        """Protocol callers must be able to pass team_id and have it work."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="t1",
                tier=MemoryTier.LESSON,
                content="team-alpha knowledge about testing",
                weight=0.6,
                org_id="org-1",
                team_id="team-alpha",
                scope=MemoryScope.TEAM,
            )
        )

        # This must work with team_id=, not team=
        results = await store.retrieve("testing", team_id="team-alpha", org_id="org-1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_protocol_signature_uses_team_id(self) -> None:
        """The EpisodicStore protocol retrieve() must accept team_id kwarg."""
        import inspect

        from stronghold.protocols.memory import EpisodicStore

        sig = inspect.signature(EpisodicStore.retrieve)
        param_names = list(sig.parameters.keys())
        assert "team_id" in param_names, (
            f"EpisodicStore.retrieve must have 'team_id' param, got: {param_names}"
        )
        assert "team" not in param_names, (
            f"EpisodicStore.retrieve must NOT have 'team' param, got: {param_names}"
        )


# ---------------------------------------------------------------------------
# H17: GLOBAL memories must not leak to callers with empty org
# ---------------------------------------------------------------------------
class TestH17GlobalScopeOrgLeakage:
    """GLOBAL memories with org_id set must not be visible to empty-org callers."""

    @pytest.mark.asyncio
    async def test_global_with_org_invisible_to_empty_caller(self) -> None:
        """A GLOBAL memory with org_id='org-alpha' must NOT be returned
        to a caller who provides no org context (empty string).
        """
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g1",
                tier=MemoryTier.WISDOM,
                content="global but org-scoped knowledge about testing",
                weight=0.9,
                org_id="org-alpha",
                scope=MemoryScope.GLOBAL,
            )
        )

        # Caller with no org context should NOT see org-scoped globals
        results = await store.retrieve("testing")
        assert results == [], "GLOBAL memory with org_id leaked to caller with no org context"

    @pytest.mark.asyncio
    async def test_global_without_org_invisible_to_empty_caller(self) -> None:
        """A truly unscoped GLOBAL memory (no org_id) must also NOT be returned
        to a caller who provides no org context -- require explicit org.
        """
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g2",
                tier=MemoryTier.WISDOM,
                content="truly global knowledge about testing",
                weight=0.9,
                org_id="",
                scope=MemoryScope.GLOBAL,
            )
        )

        # Empty caller with no org should not see any GLOBAL memories
        results = await store.retrieve("testing")
        assert results == [], "Unscoped GLOBAL memory leaked to caller with no org context"

    @pytest.mark.asyncio
    async def test_global_visible_to_matching_org(self) -> None:
        """GLOBAL memory with org_id set is visible to same-org callers."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g3",
                tier=MemoryTier.WISDOM,
                content="global org-alpha knowledge about testing",
                weight=0.9,
                org_id="org-alpha",
                scope=MemoryScope.GLOBAL,
            )
        )

        results = await store.retrieve("testing", org_id="org-alpha")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_global_no_org_visible_to_org_caller(self) -> None:
        """Unscoped GLOBAL memory (no org_id) is visible to any org caller."""
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g4",
                tier=MemoryTier.WISDOM,
                content="truly global knowledge about testing",
                weight=0.9,
                org_id="",
                scope=MemoryScope.GLOBAL,
            )
        )

        results = await store.retrieve("testing", org_id="org-alpha")
        assert len(results) == 1

    def test_matches_scope_rejects_empty_caller_org(self) -> None:
        """Direct test: _matches_scope must reject GLOBAL when caller has no org."""
        mem = EpisodicMemory(
            memory_id="g5",
            content="test",
            scope=MemoryScope.GLOBAL,
            org_id="org-alpha",
        )
        # Simulate a filter list with no org -- only GLOBAL filter present
        filters = [(MemoryScope.GLOBAL, None)]
        assert not _matches_scope(mem, filters), (
            "_matches_scope returned True for GLOBAL memory with org_id when caller has no org"
        )

    def test_matches_scope_rejects_unscoped_global_for_empty_caller(self) -> None:
        """_matches_scope must reject even unscoped GLOBAL when caller has no org."""
        mem = EpisodicMemory(
            memory_id="g6",
            content="test",
            scope=MemoryScope.GLOBAL,
            org_id="",
        )
        filters = [(MemoryScope.GLOBAL, None)]
        assert not _matches_scope(mem, filters), (
            "_matches_scope returned True for unscoped GLOBAL memory when caller has no org context"
        )
