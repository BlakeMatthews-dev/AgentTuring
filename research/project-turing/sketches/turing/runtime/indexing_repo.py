"""IndexingRepo: Repo that also maintains an EmbeddingIndex on writes.

Wraps a Repo; every insert of an I_DID memory is mirrored into the
EmbeddingIndex so semantic retrieval can find it. Non-I_DID memories
(I_IMAGINED daydreams, I_WAS_TOLD claims) are intentionally not indexed
by default — the self searches its own experience, not its imagined
or hearsay content. Callers that want those can call
`index_memory()` explicitly.
"""

from __future__ import annotations

import logging

from ..repo import Repo
from ..types import EpisodicMemory, SourceKind
from .embedding_index import EmbeddingIndex


logger = logging.getLogger("turing.runtime.indexing_repo")


class IndexingRepo:
    """Thin wrapper that mirrors inserts into an EmbeddingIndex."""

    def __init__(self, *, inner: Repo, index: EmbeddingIndex) -> None:
        self._inner = inner
        self._index = index

    # Delegate to inner repo; shadow insert to also index.
    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def insert(self, memory: EpisodicMemory) -> str:
        memory_id = self._inner.insert(memory)
        if memory.source == SourceKind.I_DID:
            self.index_memory(memory)
        return memory_id

    def index_memory(self, memory: EpisodicMemory) -> None:
        self._index.add(
            memory.memory_id,
            memory.content,
            meta={
                "self_id": memory.self_id,
                "tier": memory.tier.value,
                "source": memory.source.value,
                "intent_at_time": memory.intent_at_time,
            },
        )

    def rebuild_index_from_repo(self, self_id: str) -> int:
        """Re-embed every I_DID memory for a self_id. Called on startup so
        restarts don't need a separate vector store on disk."""
        count = 0
        for memory in self._inner.find(
            self_id=self_id,
            source=SourceKind.I_DID,
            include_superseded=True,
        ):
            self.index_memory(memory)
            count += 1
        logger.info("rebuilt embedding index with %d entries", count)
        return count
