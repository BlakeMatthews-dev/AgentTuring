"""Tests for specs/prospective-simulation.md: AC-60.*."""

from __future__ import annotations

import dataclasses

import pytest

from turing.self_prospection import (
    SURPRISE_THRESHOLD_LESSON,
    SURPRISE_THRESHOLD_QUIET,
    Prediction,
    create_prediction,
    get_timeout_count,
    mark_chosen,
    resolve_prediction,
    should_mint_lesson,
    should_mint_quiet,
)


_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS prospective_predictions (
    prediction_id TEXT PRIMARY KEY,
    self_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    candidate_specialist TEXT NOT NULL,
    predicted_outcome_summary TEXT,
    predicted_confidence REAL,
    chosen INTEGER DEFAULT 0,
    actual_outcome TEXT,
    surprise_delta REAL,
    resolved_at TEXT,
    created_at TEXT
)
"""


@pytest.fixture(autouse=True)
def _ensure_table(repo) -> None:
    repo.conn.execute(_CREATE_TABLE)
    repo.conn.commit()


# --------- AC-60.1 create_prediction inserts and returns Prediction -----------


def test_ac_60_1_create_prediction(repo, bootstrapped_id) -> None:
    pred = create_prediction(
        repo,
        self_id=bootstrapped_id,
        request_hash="hash:abc",
        candidate_specialist="artificer",
        predicted_summary="Code task completed",
        confidence=0.85,
    )
    assert isinstance(pred, Prediction)
    assert pred.prediction_id
    assert pred.self_id == bootstrapped_id
    assert pred.candidate_specialist == "artificer"
    assert pred.predicted_confidence == pytest.approx(0.85)
    assert pred.chosen is False
    row = repo.conn.execute(
        "SELECT prediction_id FROM prospective_predictions WHERE prediction_id = ?",
        (pred.prediction_id,),
    ).fetchone()
    assert row is not None


# --------- AC-60.2 mark_chosen sets chosen=1 ---------------------------------


def test_ac_60_2_mark_chosen(repo, bootstrapped_id) -> None:
    pred = create_prediction(repo, bootstrapped_id, "h1", "ranger", "search done", 0.7)
    mark_chosen(repo, pred.prediction_id)
    row = repo.conn.execute(
        "SELECT chosen FROM prospective_predictions WHERE prediction_id = ?",
        (pred.prediction_id,),
    ).fetchone()
    assert row[0] == 1


# --------- AC-60.3 resolve_prediction fills actual and surprise ---------------


def test_ac_60_3_resolve_prediction(repo, bootstrapped_id) -> None:
    pred = create_prediction(repo, bootstrapped_id, "h2", "scribe", "essay written", 0.6)
    resolve_prediction(repo, pred.prediction_id, "essay delivered", 0.42)
    row = repo.conn.execute(
        "SELECT actual_outcome, surprise_delta, resolved_at FROM prospective_predictions WHERE prediction_id = ?",
        (pred.prediction_id,),
    ).fetchone()
    assert row[0] == "essay delivered"
    assert row[1] == pytest.approx(0.42)
    assert row[2] is not None


# --------- AC-60.4 should_mint_lesson(0.6) == True ---------------------------


def test_ac_60_4_mint_lesson_high_surprise() -> None:
    assert should_mint_lesson(0.6) is True


# --------- AC-60.5 should_mint_lesson(0.3) == False --------------------------


def test_ac_60_5_mint_lesson_low_surprise() -> None:
    assert should_mint_lesson(0.3) is False


# --------- AC-60.6 should_mint_quiet(0.1) == True ----------------------------


def test_ac_60_6_mint_quiet_low_surprise() -> None:
    assert should_mint_quiet(0.1) is True


# --------- AC-60.7 Prediction dataclass has expected defaults -----------------


def test_ac_60_7_prediction_defaults() -> None:
    p = Prediction(
        prediction_id="pid",
        self_id="sid",
        request_hash="rh",
        candidate_specialist="artificer",
        predicted_outcome_summary="summary",
        predicted_confidence=0.8,
    )
    assert p.chosen is False
    assert p.actual_outcome is None
    assert p.surprise_delta is None
    assert p.resolved_at is None


# --------- AC-60.8 threshold constants ---------------------------------------


def test_ac_60_8_threshold_constants() -> None:
    assert SURPRISE_THRESHOLD_LESSON == 0.5
    assert SURPRISE_THRESHOLD_QUIET == 0.15


# --------- AC-60.9 get_timeout_count returns int -----------------------------


def test_ac_60_9_timeout_count_is_int() -> None:
    assert isinstance(get_timeout_count(), int)


# --------- AC-60.10 should_mint_lesson boundary at exactly 0.5 ---------------


def test_ac_60_10_mint_lesson_exact_threshold() -> None:
    assert should_mint_lesson(0.5) is True
