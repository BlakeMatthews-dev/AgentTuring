"""Tests for specs/durability-invariants.md: AC-3.1 through AC-3.8."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from turing.repo import ImmutableViolation, Repo
from turing.tiers import WEIGHT_BOUNDS
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _make_regret(self_id: str, *, supersedes: str | None = None) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="something I wish I hadn't done",
        weight=0.7,
        affect=-0.5,
        confidence_at_creation=0.8,
        surprise_delta=0.5,
        intent_at_time="route-a-request",
        supersedes=supersedes,
        immutable=True,
    )


def _make_stance(self_id: str, content: str = "I believe X") -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OPINION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.5,
        intent_at_time="some-intent",
    )


def test_ac_3_1_floor_preservation(repo: Repo, self_id: str) -> None:
    regret = _make_regret(self_id)
    repo.insert(regret)
    floor = WEIGHT_BOUNDS[MemoryTier.REGRET][0]
    for _ in range(100):
        new_weight = repo.decay_weight(regret.memory_id, delta=0.1)
        assert new_weight >= floor


def test_ac_3_2_immutable_cannot_be_soft_deleted(repo: Repo, self_id: str) -> None:
    regret = _make_regret(self_id)
    repo.insert(regret)
    with pytest.raises(ImmutableViolation):
        repo.soft_delete(regret.memory_id)


def test_ac_3_2_durable_cannot_be_hard_deleted(repo: Repo, self_id: str) -> None:
    regret = _make_regret(self_id)
    repo.insert(regret)
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "DELETE FROM durable_memory WHERE memory_id = ?", (regret.memory_id,)
        )


def test_ac_3_3_durable_requires_i_did_source() -> None:
    for bad_source in (SourceKind.I_WAS_TOLD, SourceKind.I_IMAGINED):
        with pytest.raises(ValueError, match="requires source=i_did"):
            EpisodicMemory(
                memory_id="x",
                self_id="self-A",
                tier=MemoryTier.REGRET,
                source=bad_source,
                content="c",
                weight=0.7,
                intent_at_time="i",
            )


def test_ac_3_4_self_binding_required() -> None:
    with pytest.raises(ValueError, match="self_id is required"):
        EpisodicMemory(
            memory_id="x",
            self_id="",
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="c",
            weight=0.7,
            intent_at_time="i",
        )


def test_ac_3_5_contradiction_mints_successor(repo: Repo, self_id: str) -> None:
    stance = _make_stance(self_id)
    repo.insert(stance)
    successor = _make_regret(self_id, supersedes=stance.memory_id)
    repo.insert(successor)
    repo.increment_contradiction_count(stance.memory_id)
    repo.set_superseded_by(stance.memory_id, successor.memory_id)

    reloaded_stance = repo.get(stance.memory_id)
    assert reloaded_stance is not None
    assert reloaded_stance.superseded_by == successor.memory_id
    assert reloaded_stance.contradiction_count == 1
    # The original stance's content is unchanged.
    assert reloaded_stance.content == stance.content


def test_ac_3_6_frozen_fields_cannot_be_mutated_in_python() -> None:
    m = EpisodicMemory(
        memory_id="x",
        self_id="self-A",
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="c",
        weight=0.7,
        intent_at_time="i",
        immutable=True,
    )
    with pytest.raises(AttributeError):
        m.content = "changed"
    with pytest.raises(AttributeError):
        m.tier = MemoryTier.ACCOMPLISHMENT


def test_ac_3_8_retrieval_quota_preserves_durable(repo: Repo, self_id: str) -> None:
    """Even with tiny total budget, at least one durable memory survives retrieval
    when one matches. Smoke test of the quota reservation; deeper property test
    in test_retrieval.py."""
    from turing.retrieval import retrieve

    regret = _make_regret(self_id)
    repo.insert(regret)

    results = retrieve(
        repo,
        self_id,
        total_budget_tokens=10,
        durable_min_tokens=50,
    )
    assert any(r.memory_id == regret.memory_id for r in results), (
        "durable memory must survive budget pressure"
    )
