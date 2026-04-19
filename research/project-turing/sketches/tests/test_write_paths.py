"""Tests for specs/write-paths.md: AC-4.1 through AC-4.6."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turing.repo import Repo, RepoError
from turing.types import EpisodicMemory, MemoryTier, SourceKind
from turing.write_paths import (
    Outcome,
    handle_accomplishment_candidate,
    handle_affirmation,
    handle_regret_candidate,
)


def _stance(self_id: str, tier: MemoryTier = MemoryTier.OPINION) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=tier,
        source=SourceKind.I_DID,
        content="I believed X",
        weight=0.5,
        intent_at_time="route-writing-request",
    )


def test_ac_4_1_regret_requires_predecessor(repo: Repo, self_id: str) -> None:
    with pytest.raises(RepoError, match="no predecessor"):
        handle_regret_candidate(
            repo,
            "nonexistent-id",
            Outcome(affect=-0.5, surprise_delta=0.5),
        )


def test_ac_4_1_regret_requires_stance_bearing_tier(repo: Repo, self_id: str) -> None:
    obs = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content="a fact",
        weight=0.3,
    )
    repo.insert(obs)
    with pytest.raises(RepoError, match="predecessor"):
        handle_regret_candidate(
            repo,
            obs.memory_id,
            Outcome(affect=-0.5, surprise_delta=0.5),
        )


def test_ac_4_1_regret_mints_successor(repo: Repo, self_id: str) -> None:
    stance = _stance(self_id)
    repo.insert(stance)
    new_id = handle_regret_candidate(
        repo,
        stance.memory_id,
        Outcome(affect=-0.6, surprise_delta=0.5),
    )
    assert new_id is not None
    regret = repo.get(new_id)
    assert regret is not None
    assert regret.tier == MemoryTier.REGRET
    assert regret.supersedes == stance.memory_id
    assert regret.immutable is True
    reloaded = repo.get(stance.memory_id)
    assert reloaded is not None
    assert reloaded.superseded_by == new_id
    assert reloaded.contradiction_count == 1


def test_ac_4_3_regret_below_threshold_does_not_fire(repo: Repo, self_id: str) -> None:
    stance = _stance(self_id)
    repo.insert(stance)
    result = handle_regret_candidate(
        repo,
        stance.memory_id,
        Outcome(affect=-0.1, surprise_delta=0.1),
    )
    assert result is None


def test_ac_4_2_accomplishment_requires_intent(repo: Repo, self_id: str) -> None:
    with pytest.raises(RepoError, match="intent"):
        handle_accomplishment_candidate(
            repo,
            self_id,
            content="I did a thing",
            intent="",
            outcome=Outcome(affect=0.5, surprise_delta=0.4),
        )


def test_ac_4_3_accomplishment_threshold(repo: Repo, self_id: str) -> None:
    below = handle_accomplishment_candidate(
        repo,
        self_id,
        content="routine success",
        intent="route-request",
        outcome=Outcome(affect=0.1, surprise_delta=0.1),
    )
    assert below is None

    above = handle_accomplishment_candidate(
        repo,
        self_id,
        content="notable success",
        intent="route-request",
        outcome=Outcome(affect=0.5, surprise_delta=0.5),
    )
    assert above is not None
    accomplishment = repo.get(above)
    assert accomplishment is not None
    assert accomplishment.tier == MemoryTier.ACCOMPLISHMENT
    assert accomplishment.immutable is True
    assert accomplishment.intent_at_time == "route-request"


def test_ac_4_4_affirmation_revocable_via_supersede(repo: Repo, self_id: str) -> None:
    first = handle_affirmation(repo, self_id, content="prefer Scribe for writing")
    first_mem = repo.get(first)
    assert first_mem is not None
    assert first_mem.immutable is False

    second = handle_affirmation(
        repo,
        self_id,
        content="prefer Artificer for writing",
        supersedes=first,
    )
    reloaded_first = repo.get(first)
    assert reloaded_first is not None
    assert reloaded_first.superseded_by == second

    second_mem = repo.get(second)
    assert second_mem is not None
    assert second_mem.supersedes == first


def test_ac_4_6_durable_writes_go_to_durable_table(
    repo: Repo, self_id: str
) -> None:
    stance = _stance(self_id)
    repo.insert(stance)
    regret_id = handle_regret_candidate(
        repo,
        stance.memory_id,
        Outcome(affect=-0.5, surprise_delta=0.5),
    )
    assert regret_id is not None

    cur = repo.conn.execute(
        "SELECT COUNT(*) FROM durable_memory WHERE memory_id = ?", (regret_id,)
    )
    assert cur.fetchone()[0] == 1
    cur = repo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE memory_id = ?", (regret_id,)
    )
    assert cur.fetchone()[0] == 0
