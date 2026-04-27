from __future__ import annotations

import pytest

from turing.self_near_dup import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    apply_merge_multiplier,
    check_near_dup,
    cosine_similarity,
)


def _embed_fn(text: str) -> list[float]:
    return [1.0, 0.0] if "art" in text else [0.0, 1.0]


EXISTING = [("p:1", "I love art")]


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1, 0], [1, 0]) == 1.0

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0


class TestCheckNearDup:
    def test_empty_existing_returns_none(self):
        nid, sim = check_near_dup(_embed_fn, [], "anything")
        assert nid is None
        assert sim == 0.0

    def test_similar_text_above_threshold(self):
        nid, sim = check_near_dup(_embed_fn, EXISTING, "I also love art")
        assert nid == "p:1"
        assert sim >= DUPLICATE_SIMILARITY_THRESHOLD

    def test_dissimilar_text_returns_none(self):
        nid, sim = check_near_dup(_embed_fn, EXISTING, "I love math")
        assert nid is None
        assert sim < DUPLICATE_SIMILARITY_THRESHOLD


class TestApplyMergeMultiplier:
    def test_pending_halves_value(self):
        assert apply_merge_multiplier(1.0, pending_merge=True) == 0.5

    def test_not_pending_returns_full(self):
        assert apply_merge_multiplier(1.0, pending_merge=False) == 1.0


class TestConstants:
    def test_threshold_value(self):
        assert DUPLICATE_SIMILARITY_THRESHOLD == 0.88
