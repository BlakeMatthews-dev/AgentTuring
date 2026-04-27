"""Tests for specs/learning-extraction-detector.md."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_learning_detector import (
    PROMOTION_HITS,
    check_promotion,
    coalesce_or_insert_candidate,
    find_regret_success_pairs,
    get_detection_counts,
)


NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_SID = "self:test-learning"


@pytest.fixture(autouse=True)
def _create_tables(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS learning_candidates ("
        "candidate_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "failed_specialist TEXT NOT NULL, succeeded_specialist TEXT NOT NULL, "
        "similarity REAL NOT NULL, hits INTEGER NOT NULL DEFAULT 1, "
        "detected_at TEXT NOT NULL, promoted_at TEXT)"
    )
    from turing import self_learning_detector as mod

    mod._DETECTION_COUNTS.clear()
    yield


def _insert_memory(repo, memory_id, tier, content, context=None):
    now = NOW.isoformat()
    repo.conn.execute(
        "INSERT INTO durable_memory "
        "(memory_id, self_id, tier, source, content, weight, affect, confidence_at_creation, "
        "surprise_delta, intent_at_time, last_accessed_at, created_at, context) "
        "VALUES (?, ?, ?, 'i_did', ?, 0.5, 0.0, 0.0, 0.0, '', ?, ?, ?)",
        (memory_id, _SID, tier, content, now, now, context),
    )
    repo.conn.commit()


def test_no_regrets_returns_empty(repo):
    assert find_regret_success_pairs(repo, _SID, NOW) == []


def test_regret_no_success_returns_empty(repo):
    _insert_memory(repo, "r1", "regret", "bad routing")
    assert find_regret_success_pairs(repo, _SID, NOW) == []


def test_regret_success_pair_found(repo):
    _insert_memory(repo, "r1", "regret", "bad routing")
    _insert_memory(repo, "s1", "affirmation", "good routing")
    pairs = find_regret_success_pairs(repo, _SID, NOW)
    assert len(pairs) == 1
    assert pairs[0]["regret_id"] == "r1"
    assert pairs[0]["success_id"] == "s1"


def test_multiple_pairs(repo):
    for i in range(3):
        _insert_memory(repo, f"r{i}", "regret", f"bad-{i}")
    for i in range(2):
        _insert_memory(repo, f"s{i}", "affirmation", f"good-{i}")
    pairs = find_regret_success_pairs(repo, _SID, NOW)
    assert len(pairs) == 3 * 2


def test_coalesce_insert_new(repo):
    cid = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    assert cid
    row = repo.conn.execute(
        "SELECT hits, failed_specialist FROM learning_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row[0] == 1
    assert row[1] == "arbiter"


def test_coalesce_increment_existing(repo):
    cid1 = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    cid2 = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.80)
    assert cid1 == cid2
    row = repo.conn.execute(
        "SELECT hits FROM learning_candidates WHERE candidate_id = ?", (cid1,)
    ).fetchone()
    assert row[0] == 2


def test_different_specialist_creates_new(repo):
    cid1 = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    cid2 = coalesce_or_insert_candidate(repo, _SID, "ranger", "scribe", 0.85)
    assert cid1 != cid2


def test_check_promotion_below_threshold(repo):
    cid = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    assert not check_promotion(repo, cid)


def test_check_promotion_at_threshold(repo):
    cid = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    for _ in range(PROMOTION_HITS - 1):
        coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.80)
    assert check_promotion(repo, cid)


def test_promote_candidate(repo):
    cid = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    from turing.self_learning_detector import promote_candidate

    promote_candidate(repo, cid)
    row = repo.conn.execute(
        "SELECT promoted_at FROM learning_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row[0] is not None


def test_promoted_candidate_not_re_promotable(repo):
    cid = coalesce_or_insert_candidate(repo, _SID, "arbiter", "artificer", 0.85)
    from turing.self_learning_detector import promote_candidate

    promote_candidate(repo, cid)
    assert not check_promotion(repo, cid)


def test_detection_counts_tracking(repo):
    _insert_memory(repo, "r1", "regret", "bad")
    _insert_memory(repo, "s1", "affirmation", "good")
    find_regret_success_pairs(repo, _SID, NOW)
    assert get_detection_counts()["pairs"] == 1


def test_unknown_candidate_returns_false(repo):
    assert not check_promotion(repo, "nonexistent-id")
