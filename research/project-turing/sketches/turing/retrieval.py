"""Retrieval with reserved quota, source filters, lineage walk. See specs/retrieval.md."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from .repo import Repo
from .types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind


DURABLE_MIN_TOKENS: int = 800


_NON_DURABLE_TIERS: frozenset[MemoryTier] = frozenset(MemoryTier) - DURABLE_TIERS


def estimate_tokens(memory: EpisodicMemory) -> int:
    """Rough token estimate: 1 token per 4 characters of content (seed heuristic)."""
    return max(1, len(memory.content) // 4)


def retrieve(
    repo: Repo,
    self_id: str,
    *,
    total_budget_tokens: int,
    source_filter: Iterable[SourceKind] | None = (SourceKind.I_DID,),
    durable_min_tokens: int = DURABLE_MIN_TOKENS,
    tiers: Iterable[MemoryTier] | None = None,
    intent_at_time: str | None = None,
) -> list[EpisodicMemory]:
    """Two-phase retrieval honoring the reserved durable quota.

    Phase 1: pull durable memories up to `durable_min_tokens`.
    Phase 2: pull non-durable memories with the remaining budget (includes
             any unused durable quota).

    Default source filter is I_DID only, per specs/retrieval.md AC-6.4.
    Callers that want I_IMAGINED (prospection) must opt in explicitly.
    """
    sources = list(source_filter) if source_filter is not None else None

    requested_tiers = set(tiers) if tiers is not None else set(MemoryTier)
    durable_tiers_to_query = requested_tiers & DURABLE_TIERS
    nondurable_tiers_to_query = requested_tiers & _NON_DURABLE_TIERS

    durable_results: list[EpisodicMemory] = []
    durable_used = 0
    if durable_tiers_to_query:
        for memory in repo.find(
            self_id=self_id,
            tiers=durable_tiers_to_query,
            sources=sources,
            intent_at_time=intent_at_time,
            include_superseded=False,
        ):
            cost = estimate_tokens(memory)
            if durable_used + cost > durable_min_tokens:
                break
            durable_results.append(memory)
            durable_used += cost

    # Remaining budget includes unused durable quota (AC-6.2).
    remaining = total_budget_tokens - durable_used

    other_results: list[EpisodicMemory] = []
    if nondurable_tiers_to_query and remaining > 0:
        other_used = 0
        for memory in repo.find(
            self_id=self_id,
            tiers=nondurable_tiers_to_query,
            sources=sources,
            intent_at_time=intent_at_time,
            include_superseded=False,
        ):
            cost = estimate_tokens(memory)
            if other_used + cost > remaining:
                break
            other_results.append(memory)
            other_used += cost

    return durable_results + other_results


def retrieve_head(repo: Repo, memory_id: str) -> EpisodicMemory | None:
    """Walk forward through `superseded_by` to the current head (AC-6.5)."""
    return repo.get_head(memory_id)


def retrieve_history(repo: Repo, memory_id: str) -> list[EpisodicMemory]:
    """Walk backward through `supersedes` returning the full chain (AC-6.5)."""
    return repo.walk_lineage(memory_id)


def _recency_weight(created_at_iso: str, now: datetime, halflife_days: float) -> float:
    """Exponential decay: 1.0 at creation, 0.5 at halflife_days, approaching 0."""
    try:
        created = datetime.fromisoformat(created_at_iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        elapsed = max(0.0, (now - created).total_seconds() / 86400.0)
        return math.exp(-elapsed * math.log(2.0) / halflife_days)
    except Exception:
        return 1.0


def semantic_retrieve(
    repo: Repo,
    index: Any,
    self_id: str,
    query: str,
    *,
    top_k: int = 8,
    tiers: Iterable[MemoryTier] | None = None,
    source_filter: Iterable[SourceKind] | None = (SourceKind.I_DID,),
    min_similarity: float = 0.1,
) -> list[tuple[EpisodicMemory, float]]:
    """Semantic top-K via the EmbeddingIndex.

    Returns `[(memory, similarity_times_weight), ...]` sorted descending.
    The score is `cosine_similarity × memory.weight` so durable memories
    with high weight outrank weakly-held (but possibly more similar)
    observations.

    Uses SQL-side filtering *after* the vector search to keep the vector
    match cheap — the alternative (filter first, then search) is expensive
    at this scale.
    """
    tier_filter = set(tiers) if tiers is not None else None
    source_set = set(source_filter) if source_filter is not None else None

    def _meta_filter(m: dict[str, Any]) -> bool:
        if m.get("self_id") != self_id:
            return False
        if tier_filter is not None and m.get("tier") not in {t.value for t in tier_filter}:
            return False
        if source_set is not None and m.get("source") not in {s.value for s in source_set}:
            return False
        return True

    hits = index.search(query, top_k=top_k * 3, filter_fn=_meta_filter)
    out: list[tuple[EpisodicMemory, float]] = []
    for memory_id, similarity, _meta in hits:
        if similarity < min_similarity:
            continue
        memory = repo.get(memory_id)
        if memory is None or memory.superseded_by is not None:
            continue
        score = similarity * memory.weight
        out.append((memory, score))
    out.sort(key=lambda t: -t[1])
    return out[:top_k]


def semantic_retrieve_recent(
    repo: Repo,
    index: Any,
    self_id: str,
    query: str,
    *,
    lookback_days: float = 30.0,
    top_k: int = 5,
    tiers: Iterable[MemoryTier] | None = None,
    source_filter: Iterable[SourceKind] | None = (SourceKind.I_DID,),
    min_similarity: float = 0.05,
    decay_halflife_days: float = 15.0,
) -> list[tuple[EpisodicMemory, float]]:
    """Semantic search over the last `lookback_days`, scored with recency decay.

    Score = cosine × weight × exp(-elapsed / halflife).
    Memories that are both topically relevant AND recent rank highest.
    """
    tier_filter = set(tiers) if tiers is not None else None
    source_set = set(source_filter) if source_filter is not None else None
    now = datetime.now(UTC)
    cutoff_iso = (now - timedelta(days=lookback_days)).isoformat()

    def _meta_filter(m: dict[str, Any]) -> bool:
        if m.get("self_id") != self_id:
            return False
        if tier_filter is not None and m.get("tier") not in {t.value for t in tier_filter}:
            return False
        if source_set is not None and m.get("source") not in {s.value for s in source_set}:
            return False
        created = m.get("created_at", "")
        return bool(created) and created >= cutoff_iso

    hits = index.search(query, top_k=top_k * 3, filter_fn=_meta_filter)
    out: list[tuple[EpisodicMemory, float]] = []
    for memory_id, similarity, meta in hits:
        if similarity < min_similarity:
            continue
        memory = repo.get(memory_id)
        if memory is None or memory.superseded_by is not None:
            continue
        rw = _recency_weight(meta.get("created_at", ""), now, decay_halflife_days)
        score = similarity * memory.weight * rw
        out.append((memory, score))
    out.sort(key=lambda t: -t[1])
    return out[:top_k]


def retrieve_session_context(
    session_index: Any,
    conversation_id: str,
    query: str,
    *,
    top_k: int = 5,
    min_similarity: float = 0.05,
) -> list[tuple[str, str, str, float]]:
    """Vector search over conversation turns from the current session.

    Returns [(turn_id, role, content, similarity)] sorted by similarity desc.
    The session_index is a separate EmbeddingIndex populated from
    conversation_turn rows; it carries meta={conversation_id, role, content}.
    """

    def _filter(m: dict[str, Any]) -> bool:
        return m.get("conversation_id") == conversation_id

    hits = session_index.search(query, top_k=top_k * 2, filter_fn=_filter)
    out: list[tuple[str, str, str, float]] = []
    for turn_id, similarity, meta in hits:
        if similarity < min_similarity:
            continue
        out.append((
            turn_id,
            meta.get("role", "user"),
            meta.get("content", ""),
            similarity,
        ))
    return out[:top_k]
