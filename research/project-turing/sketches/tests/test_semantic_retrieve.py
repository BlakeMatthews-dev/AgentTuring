"""Tests for turing/retrieval.py::semantic_retrieve and IndexingRepo."""

from __future__ import annotations

from uuid import uuid4

from turing.repo import Repo
from turing.retrieval import semantic_retrieve
from turing.runtime.embedding_index import EmbeddingIndex
from turing.runtime.indexing_repo import IndexingRepo
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _deterministic_embed(text: str) -> list[float]:
    """Each word becomes one dim of a sparse vector; shared words → similarity."""
    words = text.lower().split()
    vocab = ["memory", "routing", "poem", "code", "wisdom", "error", "idea"]
    return [1.0 if v in words else 0.0 for v in vocab]


def _mint(
    repo: Repo, self_id: str, tier: MemoryTier, content: str, *, weight: float
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=tier,
        source=SourceKind.I_DID,
        content=content,
        weight=weight,
        intent_at_time="test",
        immutable=(tier in {MemoryTier.REGRET, MemoryTier.ACCOMPLISHMENT}),
    )
    repo.insert(m)
    return m.memory_id


def test_indexing_repo_embeds_on_insert(repo: Repo, self_id: str) -> None:
    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)
    _mint(wrapped, self_id, MemoryTier.REGRET, "bad routing memory", weight=0.7)
    assert index.size() == 1


def test_indexing_repo_does_not_embed_i_imagined(repo: Repo, self_id: str) -> None:
    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.HYPOTHESIS,
        source=SourceKind.I_IMAGINED,
        content="what if",
        weight=0.3,
    )
    wrapped.insert(m)
    assert index.size() == 0


def test_semantic_retrieve_finds_related(repo: Repo, self_id: str) -> None:
    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)

    _mint(wrapped, self_id, MemoryTier.REGRET, "bad routing error", weight=0.7)
    _mint(wrapped, self_id, MemoryTier.ACCOMPLISHMENT, "good poem idea", weight=0.7)
    _mint(wrapped, self_id, MemoryTier.OPINION, "my wisdom about code", weight=0.5)

    hits = semantic_retrieve(
        repo,
        index,
        self_id=self_id,
        query="routing error",
        top_k=3,
        min_similarity=0.01,
    )
    assert hits
    top_memory, score = hits[0]
    assert "routing" in top_memory.content.lower()


def test_semantic_retrieve_source_filter_default_i_did(
    repo: Repo, self_id: str
) -> None:
    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)

    _mint(wrapped, self_id, MemoryTier.OPINION, "memory routing", weight=0.5)
    # Manually add a non-I_DID memory via index (the wrapper would not do this).
    index.add(
        "forced",
        "memory routing imagined",
        meta={"self_id": self_id, "tier": "opinion", "source": "i_imagined"},
    )
    hits = semantic_retrieve(
        repo,
        index,
        self_id=self_id,
        query="memory routing",
        top_k=5,
    )
    # Filter defaults to {I_DID}; the "forced" entry is filtered by meta.
    ids = [m.memory_id for m, _ in hits]
    assert "forced" not in ids


def test_semantic_retrieve_respects_tier_filter(
    repo: Repo, self_id: str
) -> None:
    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)

    _mint(wrapped, self_id, MemoryTier.REGRET, "memory routing", weight=0.7)
    _mint(wrapped, self_id, MemoryTier.OPINION, "memory routing", weight=0.5)

    hits = semantic_retrieve(
        repo,
        index,
        self_id=self_id,
        query="memory routing",
        top_k=5,
        tiers=[MemoryTier.REGRET],
    )
    assert all(m.tier == MemoryTier.REGRET for m, _ in hits)


def test_rebuild_index_from_repo(repo: Repo, self_id: str) -> None:
    # Insert directly into the inner repo (bypass wrapper), then rebuild.
    for i in range(3):
        m = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.OPINION,
            source=SourceKind.I_DID,
            content=f"memory #{i}",
            weight=0.5,
            intent_at_time="test",
        )
        repo.insert(m)

    index = EmbeddingIndex(embed_fn=_deterministic_embed)
    wrapped = IndexingRepo(inner=repo, index=index)
    count = wrapped.rebuild_index_from_repo(self_id)
    assert count == 3
    assert index.size() == 3
