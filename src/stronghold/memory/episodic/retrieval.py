"""Scored episodic retrieval with embedding reranking and org scoping.

In-memory version uses keyword overlap + optional embedding similarity,
weighted by the memory's confidence weight. PostgreSQL version would use
pg_trgm similarity * weight + pgvector cosine distance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stronghold.memory.learnings.embeddings import cosine_similarity
from stronghold.memory.scopes import build_scope_filter

if TYPE_CHECKING:
    from stronghold.memory.episodic.store import InMemoryEpisodicStore
    from stronghold.protocols.embeddings import EmbeddingClient
    from stronghold.types.memory import EpisodicMemory

logger = logging.getLogger("stronghold.episodic.retrieval")


class ScoredEpisodicRetrieval:
    """Retrieves episodic memories with scope filtering and similarity scoring.

    Score = text_similarity * memory_weight
    Where text_similarity is either keyword overlap or cosine similarity.
    Higher weight memories (LESSON, REGRET, WISDOM) rank above lower ones.
    """

    def __init__(
        self,
        store: InMemoryEpisodicStore,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._store = store
        self._embeddings = embedding_client

    async def retrieve(
        self,
        query: str,
        *,
        org_id: str | None = None,
        team_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered and scored.

        Scope filtering ensures org isolation: memories from org-A
        are never visible to org-B queries.
        """
        # Build scope filter from identity
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )

        # Get all non-deleted memories from store
        all_memories = [m for m in self._store._memories if not m.deleted]

        # Filter by scope
        from stronghold.memory.episodic.store import _matches_scope

        scoped = [m for m in all_memories if _matches_scope(m, scope_filters)]

        if not scoped:
            return []

        # Score by similarity * weight
        scored: list[tuple[float, EpisodicMemory]] = []

        # Try embedding-based scoring
        query_vec: list[float] | None = None
        if self._embeddings:
            try:
                query_vec = await self._embeddings.embed(query)
                if all(v == 0.0 for v in query_vec):
                    query_vec = None  # Noop client
            except Exception:
                logger.warning("Embedding query failed, falling back to keyword retrieval")
                query_vec = None

        query_words = set(query.lower().split())

        for mem in scoped:
            if query_vec:
                # Embedding-based: cosine similarity * weight
                try:
                    mem_vec = await self._embeddings.embed(mem.content)  # type: ignore[union-attr]
                    sim = cosine_similarity(query_vec, mem_vec)
                except Exception:
                    sim = self._keyword_similarity(query_words, mem.content)
            else:
                # Keyword-based: word overlap * weight
                sim = self._keyword_similarity(query_words, mem.content)

            score = sim * mem.weight
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    @staticmethod
    def _keyword_similarity(query_words: set[str], content: str) -> float:
        """Simple word overlap ratio."""
        content_words = set(content.lower().split())
        if not query_words or not content_words:
            return 0.0
        overlap = len(query_words & content_words)
        return overlap / len(query_words)
