"""Near-duplicate node detection. See specs/near-duplicate-review.md.

On every note_*, compute cosine similarity of the new text against existing
same-kind texts. Flagged rows get pending_merge_review=True with a 0.5x
activation multiplier until operator resolves.
"""

from __future__ import annotations

from .self_model import NodeKind


DUPLICATE_SIMILARITY_THRESHOLD: float = 0.88

_DETECT_COUNTS: dict[str, int] = {}


def get_detect_counts() -> dict[str, int]:
    return dict(_DETECT_COUNTS)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return min(1.0, dot / (mag_a * mag_b))


def check_near_dup(
    embed_fn,
    existing_texts: list[tuple[str, str]],
    new_text: str,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> tuple[str | None, float]:
    if not existing_texts or not new_text.strip():
        return None, 0.0
    new_embed = embed_fn(new_text)
    best_id: str | None = None
    best_sim: float = 0.0
    for node_id, text in existing_texts:
        sim = cosine_similarity(new_embed, embed_fn(text))
        if sim > best_sim:
            best_id = node_id
            best_sim = sim
    if best_sim >= threshold:
        _DETECT_COUNTS["detected"] = _DETECT_COUNTS.get("detected", 0) + 1
        return best_id, best_sim
    return None, best_sim


def apply_merge_multiplier(source_state_value: float, pending_merge: bool) -> float:
    if pending_merge:
        return source_state_value * 0.5
    return source_state_value
