"""Tests for specs/affirmation-candidacy-detector.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from turing.self_affirmation_detector import (
    MIN_HITS,
    MIN_SUCCESS_RATE,
    ack_candidate,
    compute_success_rates,
    get_candidate_counts,
    insert_candidate,
    qualifies_as_candidate,
)


NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_SID = "self:test-affirm"


@pytest.fixture(autouse=True)
def _create_tables(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS episodic_memory ("
        "memory_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, tier TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT 'i_did', "
        "content TEXT NOT NULL, weight REAL NOT NULL DEFAULT 0.5, "
        "context TEXT, intent_at_time TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)"
    )
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS affirmation_candidates ("
        "candidate_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "specialist TEXT NOT NULL, success_rate REAL NOT NULL, hits INTEGER NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', reviewed_by TEXT, "
        "reviewed_at TEXT, detected_at TEXT NOT NULL)"
    )
    from turing import self_affirmation_detector as mod

    mod._CANDIDATE_COUNTS.clear()
    yield


def _insert_routing_memory(repo, memory_id, context_dict, created_at=None):
    ctx = json.dumps(context_dict)
    ts = (created_at or NOW).isoformat()
    repo.conn.execute(
        "INSERT INTO episodic_memory "
        "(memory_id, self_id, tier, source, content, weight, affect, confidence_at_creation, "
        "surprise_delta, intent_at_time, last_accessed_at, created_at, context) "
        "VALUES (?, ?, 'observation', 'i_did', 'routing', 0.5, 0.0, 0.0, 0.0, 'route request', ?, ?, ?)",
        (memory_id, _SID, ts, ts, ctx),
    )
    repo.conn.commit()


def test_no_routing_memories_returns_empty(repo):
    assert compute_success_rates(repo, _SID, NOW) == []


def test_compute_success_rates_single_specialist(repo):
    for i in range(10):
        outcome = "ok" if i < 8 else "fail"
        _insert_routing_memory(repo, f"m{i}", {"decision": "artificer", "outcome": outcome})
    rates = compute_success_rates(repo, _SID, NOW)
    assert len(rates) == 1
    assert rates[0]["specialist"] == "artificer"
    assert rates[0]["hits"] == 10
    assert rates[0]["success_rate"] == 0.8


def test_compute_success_rates_multiple_specialists(repo):
    for i in range(5):
        _insert_routing_memory(repo, f"a{i}", {"decision": "artificer", "outcome": "ok"})
    for i in range(5):
        _insert_routing_memory(repo, f"s{i}", {"decision": "scribe", "outcome": "fail"})
    rates = compute_success_rates(repo, _SID, NOW)
    assert len(rates) == 2
    by_name = {r["specialist"]: r for r in rates}
    assert by_name["artificer"]["success_rate"] == 1.0
    assert by_name["scribe"]["success_rate"] == 0.0


def test_qualifies_below_hits(repo):
    assert not qualifies_as_candidate({"hits": MIN_HITS - 1, "success_rate": 1.0})


def test_qualifies_below_rate(repo):
    assert not qualifies_as_candidate({"hits": MIN_HITS, "success_rate": MIN_SUCCESS_RATE - 0.01})


def test_qualifies_meets_both(repo):
    assert qualifies_as_candidate({"hits": MIN_HITS, "success_rate": MIN_SUCCESS_RATE})


def test_qualifies_above_both(repo):
    assert qualifies_as_candidate({"hits": 20, "success_rate": 0.95})


def test_insert_candidate(repo):
    cid = insert_candidate(repo, _SID, "artificer", 0.92, 15)
    assert cid
    row = repo.conn.execute(
        "SELECT specialist, success_rate, hits, status FROM affirmation_candidates WHERE candidate_id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == "artificer"
    assert row[1] == 0.92
    assert row[2] == 15
    assert row[3] == "pending"


def test_ack_candidate_approved(repo):
    cid = insert_candidate(repo, _SID, "artificer", 0.92, 15)
    ack_candidate(repo, cid, "approved", "operator-1")
    row = repo.conn.execute(
        "SELECT status, reviewed_by FROM affirmation_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "approved"
    assert row[1] == "operator-1"


def test_ack_candidate_rejected(repo):
    cid = insert_candidate(repo, _SID, "artificer", 0.92, 15)
    ack_candidate(repo, cid, "rejected", "operator-1")
    row = repo.conn.execute(
        "SELECT status FROM affirmation_candidates WHERE candidate_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "rejected"


def test_candidate_counts_tracking(repo):
    insert_candidate(repo, _SID, "artificer", 0.92, 15)
    assert get_candidate_counts()["inserted"] == 1


def test_ack_counts_tracking(repo):
    cid = insert_candidate(repo, _SID, "artificer", 0.92, 15)
    ack_candidate(repo, cid, "approved", "op")
    assert get_candidate_counts()["approved"] == 1


def test_success_outcome_variants(repo):
    for outcome in ("ok", "reply_directly", "delegate"):
        _insert_routing_memory(repo, f"m_{outcome}", {"decision": "ranger", "outcome": outcome})
    rates = compute_success_rates(repo, _SID, NOW)
    assert len(rates) == 1
    assert rates[0]["success_rate"] == 1.0
    assert rates[0]["hits"] == 3
