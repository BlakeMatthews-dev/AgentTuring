"""Tests for specs/tuning.md: AC-11.1 through AC-11.11 (subset)."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from uuid import uuid4

from turing.motivation import ACTION_CADENCE_TICKS, Motivation, DispatchObservation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.tuning import (
    COEFFICIENT_COMMITMENT_PREFIX,
    CoefficientTable,
    CoefficientTuner,
    CoefficientUpdate,
    apply_update,
    parse_coefficient_commitment,
    validate_table,
)
from turing.types import EpisodicMemory, MemoryTier, SourceKind
from turing.write_paths import handle_affirmation


# -----------------------------------------------------------------------------
# AC-11.1 — CoefficientTable exposes every tunable as a named field.
# -----------------------------------------------------------------------------


def test_ac_11_1_exposes_named_fields() -> None:
    table = CoefficientTable.seed()
    expected = {
        "pressure_max",
        "pressure_rate_coefficient",
        "daydream_fire_floor",
        "regret_surprise_threshold",
        "accomplishment_bias",
    }
    actual = {f.name for f in fields(table)}
    assert expected.issubset(actual)


def test_parse_commitment_round_trip() -> None:
    update = CoefficientUpdate(name="daydream_fire_floor", value=20.0)
    content = update.to_content()
    assert content.startswith(COEFFICIENT_COMMITMENT_PREFIX)
    parsed = parse_coefficient_commitment(content)
    assert parsed.name == "daydream_fire_floor"
    assert parsed.value == 20.0


def test_apply_update_updates_field() -> None:
    table = CoefficientTable.seed()
    update = CoefficientUpdate(name="daydream_fire_floor", value=25.0)
    new_table = apply_update(table, update)
    assert new_table.daydream_fire_floor == 25.0
    # Original unchanged.
    assert table.daydream_fire_floor == 10.0


def test_apply_update_unknown_field_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown coefficient"):
        apply_update(
            CoefficientTable.seed(),
            CoefficientUpdate(name="not_a_real_field", value=1.0),
        )


# -----------------------------------------------------------------------------
# AC-11.2 — from_repo applies AFFIRMATIONs in creation order.
# -----------------------------------------------------------------------------


def test_ac_11_2_from_repo_applies_affirmations_in_order(repo: Repo, self_id: str) -> None:
    handle_affirmation(
        repo,
        self_id,
        content=CoefficientUpdate("daydream_fire_floor", 15.0).to_content(),
    )
    first_id = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
        )
    )[0].memory_id

    handle_affirmation(
        repo,
        self_id,
        content=CoefficientUpdate("daydream_fire_floor", 30.0).to_content(),
        supersedes=first_id,
    )

    table = CoefficientTable.from_repo(repo, self_id)
    # Only the non-superseded (second) one is applied.
    assert table.daydream_fire_floor == 30.0


# -----------------------------------------------------------------------------
# AC-11.3 — out-of-range value rejected at load; table falls back.
# -----------------------------------------------------------------------------


def test_ac_11_3_out_of_range_rejected_at_load(repo: Repo, self_id: str) -> None:
    handle_affirmation(
        repo,
        self_id,
        content=CoefficientUpdate(
            "regret_affect_threshold",
            5.0,  # out of [0,1]
        ).to_content(),
    )
    table = CoefficientTable.from_repo(repo, self_id)
    assert table.regret_affect_threshold == CoefficientTable.seed().regret_affect_threshold


def test_validate_table_catches_out_of_range() -> None:
    table = CoefficientTable(accomplishment_bias=5.0)  # out of [0,1]
    assert validate_table(table) is False


# -----------------------------------------------------------------------------
# AC-11.7 — tuner submits candidate periodically.
# -----------------------------------------------------------------------------


def test_ac_11_7_tuner_submits_on_cadence(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    tuner = CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
        cadence_ticks=5,
        min_observations_before_submit=0,
    )

    reactor.tick(1)  # submits first candidate (tick - 0 >= 5? yes at 5)
    # Cadence is 5 ticks; first submission happens when tick >= 5.
    reactor.tick(4)
    matching = [b for b in motivation.backlog if b.kind == "tuning_candidate"]
    assert len(matching) == 1


# -----------------------------------------------------------------------------
# AC-11.9 — below threshold: no proposal.
# AC-11.10 — proposal is committed as an AFFIRMATION.
# -----------------------------------------------------------------------------


def test_ac_11_9_no_proposal_without_enough_observations(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    tuner = CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
        cadence_ticks=1,
        min_observations=100,
    )

    # Submit one candidate, let it dispatch. Observation count too low.
    reactor.tick(ACTION_CADENCE_TICKS + 1)

    affirmations = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
        )
    )
    assert affirmations == []


def test_ac_11_10_proposal_written_as_affirmation(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)

    # Preseed enough synthetic observations to pass min_observations
    # and trigger the daydream-low-rate signal (returns a proposal).
    for i in range(60):
        motivation._observations.append(  # type: ignore[attr-defined]
            DispatchObservation(
                item_id=f"x-{i}",
                kind="user_request",
                class_=3,
                chosen_pool="general",
                score=100.0,
                pressure_snapshot={"general": 10.0},
                fit_snapshot={"general": 1.0},
                decided_at=datetime.now(UTC),
            )
        )

    tuner = CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
        cadence_ticks=1,
        min_observations=10,
    )

    # Let the tuning candidate be submitted and dispatched.
    reactor.tick(ACTION_CADENCE_TICKS)

    affirmations = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
            include_superseded=False,
        )
    )
    assert len(affirmations) >= 1
    assert all(a.content.startswith(COEFFICIENT_COMMITMENT_PREFIX) for a in affirmations)
