"""Tests for specs/operator-coaching-channel.md."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_coaching import (
    OVER_COACHING_THRESHOLD,
    OVER_COACHING_WINDOW_HOURS,
    check_over_coaching,
    coach_self,
    sign_coaching,
    verify_coaching_signature,
)


_SID = "self:test-coaching"


@pytest.fixture(autouse=True)
def _create_tables(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS self_coaching_log ("
        "coaching_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "content TEXT NOT NULL, tier TEXT NOT NULL, operator_id TEXT NOT NULL, "
        "signature TEXT NOT NULL, over_coached INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL)"
    )


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-coaching-key-123")


def test_sign_verify_roundtrip():
    now = datetime.now(UTC).isoformat()
    sig = sign_coaching("hello", "op-1", now)
    assert verify_coaching_signature("hello", "op-1", now, sig)


def test_tampered_content_fails():
    now = datetime.now(UTC).isoformat()
    sig = sign_coaching("original", "op-1", now)
    assert not verify_coaching_signature("tampered", "op-1", now, sig)


def test_wrong_operator_fails():
    now = datetime.now(UTC).isoformat()
    sig = sign_coaching("hello", "op-1", now)
    assert not verify_coaching_signature("hello", "op-2", now, sig)


def test_wrong_timestamp_fails():
    sig = sign_coaching("hello", "op-1", "2026-01-01T00:00:00+00:00")
    assert not verify_coaching_signature("hello", "op-1", "2026-01-02T00:00:00+00:00", sig)


def test_coach_self_inserts(repo):
    cid = coach_self(repo, _SID, content="Be more concise", tier="OPINION", operator_id="op-1")
    assert cid
    row = repo.conn.execute(
        "SELECT content, tier, operator_id, over_coached FROM self_coaching_log WHERE coaching_id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == "Be more concise"
    assert row[1] == "OPINION"
    assert row[2] == "op-1"
    assert row[3] == 0


def test_coach_self_default_tier(repo):
    cid = coach_self(repo, _SID, content="test content")
    row = repo.conn.execute(
        "SELECT tier FROM self_coaching_log WHERE coaching_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "OPINION"


def test_coach_self_signature_stored(repo):
    cid = coach_self(repo, _SID, content="hello", operator_id="op-1")
    row = repo.conn.execute(
        "SELECT signature FROM self_coaching_log WHERE coaching_id = ?", (cid,)
    ).fetchone()
    assert row[0]
    assert len(row[0]) == 64


def test_check_over_coaching_below_threshold(repo):
    for i in range(OVER_COACHING_THRESHOLD - 1):
        coach_self(repo, _SID, content=f"msg-{i}")
    assert not check_over_coaching(repo, _SID)


def test_check_over_coaching_at_threshold(repo):
    for i in range(OVER_COACHING_THRESHOLD):
        coach_self(repo, _SID, content=f"msg-{i}")
    assert check_over_coaching(repo, _SID)


def test_over_coached_flag_set(repo):
    for i in range(OVER_COACHING_THRESHOLD):
        coach_self(repo, _SID, content=f"msg-{i}")
    cid = coach_self(repo, _SID, content="over limit")
    row = repo.conn.execute(
        "SELECT over_coached FROM self_coaching_log WHERE coaching_id = ?", (cid,)
    ).fetchone()
    assert row[0] == 1


def test_coach_self_skip_mood_no_effect_on_insert(repo):
    cid = coach_self(repo, _SID, content="silent", skip_mood=True)
    assert cid
