"""Episodic memory store. In-memory for testing, PostgreSQL+pgvector for production."""

from __future__ import annotations

from stronghold.memory.scopes import build_scope_filter
from stronghold.types.memory import EpisodicMemory, MemoryScope


def _matches_scope(
    mem: EpisodicMemory,
    filters: list[tuple[str, str | None]],
) -> bool:
    """Check if a memory matches any of the scope filters.

    Hierarchy: GLOBAL > ORGANIZATION > TEAM > USER > AGENT > SESSION

    CRITICAL: Team scope requires BOTH team_id AND org_id match to prevent
    cross-org leakage when different orgs have teams with the same name.
    """
    # Build a lookup of what the caller provided
    caller_org = ""
    for scope, value in filters:
        if scope == MemoryScope.ORGANIZATION and value:
            caller_org = value

    for scope, value in filters:
        if scope == MemoryScope.GLOBAL and mem.scope == MemoryScope.GLOBAL:
            # H17: GLOBAL memories require explicit org context to prevent
            # cross-tenant leakage. A caller with no org_id must not see
            # any GLOBAL memories -- neither org-scoped nor unscoped ones.
            if not caller_org:
                continue  # No org context = no GLOBAL visibility
            # If the memory is org-scoped, it must match the caller's org.
            # Unscoped GLOBAL memories (org_id="") are visible to any org caller.
            if mem.org_id and mem.org_id != caller_org:
                continue  # Different org's global memory -- skip
            return True
        if mem.scope != scope:
            continue
        if scope == MemoryScope.ORGANIZATION and mem.org_id == value:
            return True
        # Team match requires BOTH team_id AND org_id to prevent cross-org leakage
        if scope == MemoryScope.TEAM and mem.team_id == value and mem.org_id == caller_org:
            return True
        if scope == MemoryScope.USER and mem.user_id == value:
            return True
        if scope == MemoryScope.AGENT and mem.agent_id == value:
            return True
    return False


class InMemoryEpisodicStore:
    """In-memory episodic store for testing."""

    def __init__(self) -> None:
        self._memories: list[EpisodicMemory] = []

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory."""
        self._memories.append(memory)
        return memory.memory_id

    async def retrieve(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        task_type: str = "",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered.

        Simple keyword matching for in-memory. PostgreSQL uses pg_trgm.
        """
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )
        query_lower = query.lower()

        results: list[tuple[float, EpisodicMemory]] = []
        for mem in self._memories:
            if mem.deleted:
                continue

            # Check scope visibility
            if not _matches_scope(mem, scope_filters):
                continue

            # Simple similarity: count word overlap
            mem_words = set(mem.content.lower().split())
            query_words = set(query_lower.split())
            overlap = len(mem_words & query_words)
            if overlap > 0:
                score = overlap * mem.weight
                results.append((score, mem))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None:
        """Reinforce a memory."""
        from stronghold.memory.episodic.tiers import reinforce

        for i, mem in enumerate(self._memories):
            if mem.memory_id == memory_id:
                self._memories[i] = reinforce(mem, delta)
                break
