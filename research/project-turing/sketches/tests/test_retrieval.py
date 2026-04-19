"""Tests for specs/retrieval.md: AC-6.1 through AC-6.6."""

from __future__ import annotations

from uuid import uuid4

from turing.repo import Repo
from turing.retrieval import retrieve, retrieve_head, retrieve_history
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mem(
    self_id: str,
    tier: MemoryTier,
    *,
    content: str = "x" * 40,    # ~10 tokens
    source: SourceKind = SourceKind.I_DID,
    intent: str = "",
    weight: float | None = None,
) -> EpisodicMemory:
    from turing.tiers import WEIGHT_BOUNDS

    lo, _ = WEIGHT_BOUNDS[tier]
    return EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=tier,
        source=source,
        content=content,
        weight=weight if weight is not None else lo + 0.05,
        intent_at_time=intent
        or ("required-for-accomplishment" if tier == MemoryTier.ACCOMPLISHMENT else ""),
    )


def test_ac_6_1_reserved_quota_favors_durable(repo: Repo, self_id: str) -> None:
    # Fill with many non-durable; one durable.
    for _ in range(50):
        repo.insert(_mem(self_id, MemoryTier.OBSERVATION))
    durable = _mem(
        self_id,
        MemoryTier.REGRET,
        intent="route-thing",
        weight=0.8,
    )
    repo.insert(durable)

    # Tiny total budget would normally not fit the durable if priority were FIFO.
    results = retrieve(repo, self_id, total_budget_tokens=20, durable_min_tokens=20)
    assert any(r.memory_id == durable.memory_id for r in results)


def test_ac_6_2_unused_durable_quota_released_to_others(
    repo: Repo, self_id: str
) -> None:
    # Only one small durable; plenty of non-durable.
    repo.insert(_mem(self_id, MemoryTier.REGRET, intent="i", content="tiny"))
    for _ in range(20):
        repo.insert(_mem(self_id, MemoryTier.OBSERVATION))

    results = retrieve(repo, self_id, total_budget_tokens=500, durable_min_tokens=200)
    # Durable quota not fully used (content="tiny" ~ 1 token); remainder to others.
    assert len(results) > 1


def test_ac_6_3_source_filter_excludes_other_sources(
    repo: Repo, self_id: str
) -> None:
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_DID))
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_WAS_TOLD))
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_IMAGINED))

    results = retrieve(
        repo,
        self_id,
        total_budget_tokens=1000,
        source_filter=(SourceKind.I_DID,),
    )
    assert all(r.source == SourceKind.I_DID for r in results)


def test_ac_6_4_default_source_is_i_did_only(repo: Repo, self_id: str) -> None:
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_DID))
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_WAS_TOLD))
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_IMAGINED))

    results = retrieve(repo, self_id, total_budget_tokens=1000)
    assert all(r.source == SourceKind.I_DID for r in results)


def test_ac_6_4_explicit_include_i_imagined(repo: Repo, self_id: str) -> None:
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_DID))
    repo.insert(_mem(self_id, MemoryTier.OBSERVATION, source=SourceKind.I_IMAGINED))

    results = retrieve(
        repo,
        self_id,
        total_budget_tokens=1000,
        source_filter=(SourceKind.I_DID, SourceKind.I_IMAGINED),
    )
    sources = {r.source for r in results}
    assert SourceKind.I_IMAGINED in sources
    assert SourceKind.I_DID in sources


def test_ac_6_5_retrieve_head_walks_forward(repo: Repo, self_id: str) -> None:
    first = _mem(self_id, MemoryTier.OPINION)
    repo.insert(first)
    second = _mem(self_id, MemoryTier.OPINION)
    # Replace the stale memory_id field via construction.
    second2 = EpisodicMemory(
        memory_id=second.memory_id,
        self_id=second.self_id,
        tier=second.tier,
        source=second.source,
        content=second.content,
        weight=second.weight,
        intent_at_time=second.intent_at_time,
        supersedes=first.memory_id,
    )
    repo.insert(second2)
    repo.set_superseded_by(first.memory_id, second2.memory_id)

    head = retrieve_head(repo, first.memory_id)
    assert head is not None
    assert head.memory_id == second2.memory_id


def test_ac_6_5_retrieve_history_walks_backward(repo: Repo, self_id: str) -> None:
    a = _mem(self_id, MemoryTier.OPINION, content="a")
    repo.insert(a)
    b = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OPINION,
        source=SourceKind.I_DID,
        content="b",
        weight=0.5,
        supersedes=a.memory_id,
    )
    repo.insert(b)
    repo.set_superseded_by(a.memory_id, b.memory_id)
    c = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OPINION,
        source=SourceKind.I_DID,
        content="c",
        weight=0.5,
        supersedes=b.memory_id,
    )
    repo.insert(c)
    repo.set_superseded_by(b.memory_id, c.memory_id)

    chain = retrieve_history(repo, c.memory_id)
    assert [m.content for m in chain] == ["a", "b", "c"]
