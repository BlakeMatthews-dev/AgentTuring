"""Tests for runtime/embedding_index.py."""

from __future__ import annotations

from turing.runtime.embedding_index import EmbeddingIndex, _cosine


def test_cosine_identical_vectors_is_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert abs(_cosine(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_is_zero() -> None:
    assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_handles_zero_vector() -> None:
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert _cosine([], []) == 0.0
    assert _cosine([1.0], [1.0, 1.0]) == 0.0   # mismatched length


def test_index_add_and_search_finds_self() -> None:
    called: dict[str, list[float]] = {
        "match": [1.0, 0.0, 0.0],
        "other": [0.0, 1.0, 0.0],
        "third": [0.0, 0.0, 1.0],
    }

    def _embed(text: str) -> list[float]:
        return called[text]

    index = EmbeddingIndex(embed_fn=_embed)
    index.add("m1", "match", meta={"tag": "a"})
    index.add("m2", "other", meta={"tag": "b"})
    index.add("m3", "third", meta={"tag": "c"})

    hits = index.search("match", top_k=2)
    assert hits[0][0] == "m1"
    assert hits[0][1] > 0.99


def test_index_filter_function() -> None:
    embeddings = {
        "a": [1.0, 0.0],
        "b": [0.9, 0.1],
        "c": [0.8, 0.2],
    }

    def _embed(t: str) -> list[float]:
        return embeddings[t]

    index = EmbeddingIndex(embed_fn=_embed)
    index.add("m1", "a", meta={"tier": "regret"})
    index.add("m2", "b", meta={"tier": "observation"})
    index.add("m3", "c", meta={"tier": "regret"})

    hits = index.search("a", top_k=5, filter_fn=lambda m: m["tier"] == "regret")
    ids = {h[0] for h in hits}
    assert ids == {"m1", "m3"}


def test_index_embed_failure_is_safe() -> None:
    def _embed(_: str) -> list[float]:
        raise RuntimeError("fake failure")

    index = EmbeddingIndex(embed_fn=_embed)
    # Should not raise.
    index.add("m1", "something", meta={})
    assert index.size() == 0
    assert index.search("anything") == []


def test_index_remove() -> None:
    def _embed(t: str) -> list[float]:
        return [1.0]

    index = EmbeddingIndex(embed_fn=_embed)
    index.add("m1", "x")
    assert index.size() == 1
    index.remove("m1")
    assert index.size() == 0
