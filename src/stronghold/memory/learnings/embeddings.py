"""Embedding-based hybrid search for learnings.

Combines keyword matching (fast, zero-cost) with cosine similarity
on embedding vectors (semantic, requires embedding client).

Graceful fallback: if no embedding client is configured or it fails,
reverts to keyword-only search. Same API as InMemoryLearningStore.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.memory.learnings.store import InMemoryLearningStore
    from stronghold.protocols.embeddings import EmbeddingClient
    from stronghold.types.memory import Learning

logger = logging.getLogger("stronghold.embeddings")

# Keyword score + embedding score weighting (matches Conductor: 1:3 ratio)
KEYWORD_WEIGHT = 1.0
EMBEDDING_WEIGHT = 3.0
MIN_COMBINED_SCORE = 0.3


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 for zero-length or mismatched vectors.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class NoopEmbeddingClient:
    """Returns zero vectors. For testing when no embedding model is available."""

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dimension for _ in texts]


class FakeEmbeddingClient:
    """Returns deterministic vectors based on text hash. For testing hybrid search.

    Uses hashlib.md5 (NOT Python's built-in hash()) so the output is
    stable across processes. The previous version used hash() which is
    randomized per process via PYTHONHASHSEED — this caused the
    test_find_relevant_embeds_uncached_learnings test to flake roughly
    1 run in 256, because some hash seeds happened to produce an
    all-zero embedding for the query string, which then tripped the
    `all(v == 0.0)` noop-client check in HybridLearningStore.find_relevant
    and early-returned without populating the embedding cache.

    Switching to md5 keeps the fake deterministic across runs and
    eliminates the all-zero vector path entirely (md5 of any non-empty
    string has non-zero bits).
    """

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        import hashlib

        digest = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).digest()  # noqa: S324
        # Pull bits from the digest deterministically. The +0.001
        # ensures the vector is never strict-all-zero (which would
        # trip the noop-client check in find_relevant).
        return [
            float(((digest[i % len(digest)] >> (i % 8)) & 1) + 0.001)
            for i in range(self._dimension)
        ]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


class HybridLearningStore:
    """Wraps InMemoryLearningStore with embedding-based hybrid search.

    Delegates all writes to the underlying store. Enhances find_relevant()
    with cosine similarity scoring when an embedding client is available.
    """

    def __init__(
        self,
        store: InMemoryLearningStore,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._store = store
        self._embeddings = embedding_client
        # Cache: learning_id → embedding vector
        self._embedding_cache: dict[int, list[float]] = {}

    async def store(self, learning: Learning) -> int:
        """Store a learning and compute its embedding."""
        learning_id = await self._store.store(learning)
        if self._embeddings and learning.learning:
            try:
                vec = await self._embeddings.embed(learning.learning)
                self._embedding_cache[learning_id] = vec
            except Exception:
                logger.warning("Embedding failed for learning #%s, keyword-only", learning_id)
        return learning_id

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Hybrid search: keyword score + embedding cosine similarity.

        Combined score = keyword_score * KEYWORD_WEIGHT + cosine_sim * EMBEDDING_WEIGHT
        Falls back to keyword-only if embedding client unavailable.
        """
        # Get keyword results from underlying store (org_id forwarded for tenant isolation)
        keyword_results = await self._store.find_relevant(
            user_text,
            agent_id=agent_id,
            org_id=org_id,
            max_results=max_results * 2,
        )

        if not self._embeddings or not keyword_results:
            return keyword_results[:max_results]

        # Get query embedding
        try:
            query_vec = await self._embeddings.embed(user_text)
        except Exception:
            logger.debug("Query embedding failed, falling back to keyword-only")
            return keyword_results[:max_results]

        # All zeros = noop client, skip reranking
        if all(v == 0.0 for v in query_vec):
            return keyword_results[:max_results]

        # Score each result with hybrid score
        scored: list[tuple[float, Learning]] = []
        for i, learning in enumerate(keyword_results):
            # Keyword score: position-based (higher rank = higher score)
            kw_score = (len(keyword_results) - i) / len(keyword_results)

            # Embedding score
            embed_score = 0.0
            if learning.id is not None and learning.id in self._embedding_cache:
                embed_score = cosine_similarity(query_vec, self._embedding_cache[learning.id])
            elif learning.learning and self._embeddings:
                try:
                    vec = await self._embeddings.embed(learning.learning)
                    embed_score = cosine_similarity(query_vec, vec)
                    if learning.id is not None:
                        self._embedding_cache[learning.id] = vec
                except Exception:
                    pass

            combined = kw_score * KEYWORD_WEIGHT + embed_score * EMBEDDING_WEIGHT
            if combined >= MIN_COMBINED_SCORE:
                scored.append((combined, learning))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    # Delegate all other methods to underlying store
    async def mark_used(self, learning_ids: list[int]) -> None:
        await self._store.mark_used(learning_ids)

    async def check_auto_promotions(
        self, threshold: int = 5, *, org_id: str = ""
    ) -> list[Learning]:
        return await self._store.check_auto_promotions(threshold, org_id=org_id)

    async def get_promoted(
        self, task_type: str | None = None, *, org_id: str = ""
    ) -> list[Learning]:
        return await self._store.get_promoted(task_type, org_id=org_id)
