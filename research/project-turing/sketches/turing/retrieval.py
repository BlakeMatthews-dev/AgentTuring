"""Retrieval with reserved quota, source filters, lineage walk. See specs/retrieval.md."""

from __future__ import annotations

from collections.abc import Iterable

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
