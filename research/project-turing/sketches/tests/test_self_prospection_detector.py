"""Tests for specs/prospection-accuracy-detector.md."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_prospection_detector import (
    CALIBRATION_THRESHOLD,
    MIN_SAMPLES,
    SURPRISE_THRESHOLD,
    TUNER_SAMPLES,
    compute_specialist_stats,
    get_agg_counts,
    should_mint_lesson,
    should_propose_tuner,
    upsert_agg,
)


NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_SID = "self:test-prosp"


@pytest.fixture(autouse=True)
def _create_tables(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS prospective_predictions ("
        "prediction_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "candidate_specialist TEXT NOT NULL, predicted_confidence REAL NOT NULL, "
        "surprise_delta REAL, resolved_at TEXT)"
    )
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS prospection_accuracy_agg ("
        "agg_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, specialist TEXT NOT NULL, "
        "n INTEGER NOT NULL, mean_surprise REAL NOT NULL, std_surprise REAL NOT NULL, "
        "calibration_error REAL NOT NULL, updated_at TEXT NOT NULL)"
    )
    from turing import self_prospection_detector as mod

    mod._AGG_COUNTS.clear()
    yield


def _insert_prediction(repo, specialist, confidence, surprise, resolved_at=None):
    from uuid import uuid4

    repo.conn.execute(
        "INSERT INTO prospective_predictions (prediction_id, self_id, candidate_specialist, "
        "predicted_confidence, surprise_delta, resolved_at) VALUES (?,?,?,?,?,?)",
        (str(uuid4()), _SID, specialist, confidence, surprise, (resolved_at or NOW).isoformat()),
    )
    repo.conn.commit()


def test_no_predictions_returns_zero_stats(repo):
    stats = compute_specialist_stats(repo, _SID, "artificer")
    assert stats["n"] == 0
    assert stats["mean_surprise"] == 0.0


def test_compute_stats_single_specialist(repo):
    for s in [0.1, 0.2, 0.15]:
        _insert_prediction(repo, "artificer", 0.8, s)
    stats = compute_specialist_stats(repo, _SID, "artificer")
    assert stats["n"] == 3
    assert abs(stats["mean_surprise"] - 0.15) < 0.01


def test_compute_stats_std(repo):
    for s in [0.0, 0.5, 1.0]:
        _insert_prediction(repo, "artificer", 0.5, s)
    stats = compute_specialist_stats(repo, _SID, "artificer")
    assert stats["n"] == 3
    assert abs(stats["std_surprise"] - (1 / 6) ** 0.5) < 0.01


def test_compute_stats_calibration(repo):
    for i in range(5):
        _insert_prediction(repo, "artificer", 0.9, 0.2)
    stats = compute_specialist_stats(repo, _SID, "artificer")
    expected_error = abs(0.9 - (1.0 - 0.2))
    assert abs(stats["calibration_error"] - expected_error) < 0.01


def test_compute_stats_different_specialist_ignored(repo):
    _insert_prediction(repo, "artificer", 0.8, 0.1)
    _insert_prediction(repo, "scribe", 0.5, 0.9)
    stats = compute_specialist_stats(repo, _SID, "artificer")
    assert stats["n"] == 1


def test_should_mint_lesson_below_samples(repo):
    assert not should_mint_lesson(
        {"n": MIN_SAMPLES - 1, "mean_surprise": 0.5, "calibration_error": 0.5}
    )


def test_should_mint_lesson_high_surprise(repo):
    assert should_mint_lesson(
        {"n": MIN_SAMPLES, "mean_surprise": SURPRISE_THRESHOLD + 0.01, "calibration_error": 0.0}
    )


def test_should_mint_lesson_high_calibration(repo):
    assert should_mint_lesson(
        {"n": MIN_SAMPLES, "mean_surprise": 0.0, "calibration_error": CALIBRATION_THRESHOLD + 0.01}
    )


def test_should_not_mint_lesson_low_both(repo):
    assert not should_mint_lesson(
        {"n": MIN_SAMPLES, "mean_surprise": 0.1, "calibration_error": 0.1}
    )


def test_should_propose_tuner_below_samples(repo):
    assert not should_propose_tuner({"n": TUNER_SAMPLES - 1, "mean_surprise": 0.5})


def test_should_propose_tuner_high_surprise(repo):
    assert should_propose_tuner({"n": TUNER_SAMPLES, "mean_surprise": 0.4})


def test_should_not_propose_tuner_low_surprise(repo):
    assert not should_propose_tuner({"n": TUNER_SAMPLES, "mean_surprise": 0.2})


def test_upsert_agg_insert(repo):
    stats = {"n": 5, "mean_surprise": 0.2, "std_surprise": 0.1, "calibration_error": 0.15}
    upsert_agg(repo, _SID, "artificer", stats)
    row = repo.conn.execute(
        "SELECT n, mean_surprise FROM prospection_accuracy_agg WHERE self_id = ? AND specialist = ?",
        (_SID, "artificer"),
    ).fetchone()
    assert row is not None
    assert row[0] == 5


def test_upsert_agg_update(repo):
    stats1 = {"n": 5, "mean_surprise": 0.2, "std_surprise": 0.1, "calibration_error": 0.15}
    upsert_agg(repo, _SID, "artificer", stats1)
    stats2 = {"n": 10, "mean_surprise": 0.3, "std_surprise": 0.15, "calibration_error": 0.2}
    upsert_agg(repo, _SID, "artificer", stats2)
    rows = repo.conn.execute(
        "SELECT n FROM prospection_accuracy_agg WHERE self_id = ? AND specialist = ?",
        (_SID, "artificer"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 10


def test_upsert_agg_counts(repo):
    upsert_agg(
        repo,
        _SID,
        "a",
        {"n": 1, "mean_surprise": 0.0, "std_surprise": 0.0, "calibration_error": 0.0},
    )
    assert get_agg_counts()["upserted"] == 1
