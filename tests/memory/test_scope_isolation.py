"""Tests for memory scope isolation."""

import pytest

from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier


class TestScopeIsolation:
    @pytest.mark.asyncio
    async def test_global_visible_to_all(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g1",
                tier=MemoryTier.WISDOM,
                content="global knowledge about testing",
                weight=0.9,
                scope=MemoryScope.GLOBAL,
            )
        )
        # Both agents within the same org should see it (H17: org context required)
        results_a = await store.retrieve("testing", agent_id="agent-a", org_id="org-1")
        results_b = await store.retrieve("testing", agent_id="agent-b", org_id="org-1")
        assert len(results_a) == 1
        assert len(results_b) == 1

    @pytest.mark.asyncio
    async def test_agent_scoped_invisible_to_other_agents(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="a1",
                tier=MemoryTier.LESSON,
                content="agent-a learned about testing",
                weight=0.6,
                agent_id="agent-a",
                scope=MemoryScope.AGENT,
            )
        )
        results_a = await store.retrieve("testing", agent_id="agent-a")
        results_b = await store.retrieve("testing", agent_id="agent-b")
        assert len(results_a) == 1
        assert len(results_b) == 0  # agent-b cannot see agent-a's memories

    @pytest.mark.asyncio
    async def test_user_scoped_visible_across_agents(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="u1",
                tier=MemoryTier.LESSON,
                content="user blake prefers concise answers about testing",
                weight=0.6,
                user_id="blake",
                scope=MemoryScope.USER,
            )
        )
        results = await store.retrieve("testing", agent_id="any-agent", user_id="blake")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_user_scoped_invisible_to_other_users(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="u1",
                tier=MemoryTier.LESSON,
                content="user blake likes testing",
                weight=0.6,
                user_id="blake",
                scope=MemoryScope.USER,
            )
        )
        results = await store.retrieve("testing", user_id="other-user")
        assert len(results) == 0


class TestTeamScope:
    @pytest.mark.asyncio
    async def test_team_scoped_visible_to_team(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="t1",
                tier=MemoryTier.LESSON,
                content="team knowledge about testing",
                weight=0.6,
                org_id="org-1",
                team_id="engineering",
                scope=MemoryScope.TEAM,
            )
        )
        results = await store.retrieve("testing", team_id="engineering", org_id="org-1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_team_scoped_invisible_to_other_team(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="t1",
                tier=MemoryTier.LESSON,
                content="team knowledge about testing",
                weight=0.6,
                org_id="org-1",
                team_id="engineering",
                scope=MemoryScope.TEAM,
            )
        )
        results = await store.retrieve("testing", team_id="marketing", org_id="org-1")
        assert len(results) == 0


class TestMixedScopes:
    @pytest.mark.asyncio
    async def test_global_plus_agent_returned(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(
            EpisodicMemory(
                memory_id="g1",
                tier=MemoryTier.WISDOM,
                content="global testing fact",
                weight=0.9,
                scope=MemoryScope.GLOBAL,
            )
        )
        await store.store(
            EpisodicMemory(
                memory_id="a1",
                tier=MemoryTier.LESSON,
                content="agent testing lesson",
                weight=0.6,
                agent_id="agent-x",
                scope=MemoryScope.AGENT,
            )
        )
        # H17: org context required for GLOBAL visibility
        results = await store.retrieve("testing", agent_id="agent-x", org_id="org-1")
        assert len(results) == 2
