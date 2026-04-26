"""Tests for specs/sentinel-self-interaction.md: AC-62.*."""

from __future__ import annotations

import pytest

from turing.self_sentinel import (
    SentinelRecord,
    SentinelVerdict,
    gate_through_sentinel,
    get_verdict_counts,
    mood_nudge_for_verdict,
    record_sentinel_verdict,
    sentinel_activation_weight,
    specialist_block_rate,
)


@pytest.fixture(autouse=True)
def _ensure_sentinel_schema(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS specialist_sentinel_record ("
        "record_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "specialist TEXT NOT NULL, verdict TEXT NOT NULL, "
        "category TEXT NOT NULL, request_hash TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL)"
    )
    repo.conn.commit()


# AC-62.1
def test_ac_62_1_verdict_enum_members():
    assert SentinelVerdict.PASS == "pass"
    assert SentinelVerdict.WARN == "warn"
    assert SentinelVerdict.BLOCK == "block"


# AC-62.2
def test_ac_62_2_record_sentinel_verdict_inserts_and_returns(repo, self_id, new_id):
    record = record_sentinel_verdict(
        repo,
        self_id,
        "ranger",
        "block",
        "security",
        new_id("hash"),
    )
    assert isinstance(record, SentinelRecord)
    assert record.self_id == self_id
    assert record.specialist == "ranger"
    assert record.verdict == "block"
    row = repo.conn.execute(
        "SELECT verdict FROM specialist_sentinel_record WHERE record_id = ?",
        (record.record_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "block"


# AC-62.3
def test_ac_62_3_block_rate_no_records(repo, self_id):
    assert specialist_block_rate(repo, self_id, "ranger") == 0.0


# AC-62.4
def test_ac_62_4_block_rate_two_of_four(repo, self_id, new_id):
    for v in ("block", "block", "pass", "warn"):
        record_sentinel_verdict(
            repo,
            self_id,
            "ranger",
            v,
            "cat",
            new_id("hash"),
        )
    assert specialist_block_rate(repo, self_id, "ranger") == 0.5


# AC-62.5
def test_ac_62_5_activation_weight_half():
    assert sentinel_activation_weight(0.5) == -0.25


# AC-62.6
def test_ac_62_6_activation_weight_capped():
    assert sentinel_activation_weight(2.0) == -0.5


# AC-62.7
def test_ac_62_7_mood_nudge_block():
    assert mood_nudge_for_verdict("block") == (-0.15, 0.10, -0.10)


# AC-62.8
def test_ac_62_8_mood_nudge_warn():
    assert mood_nudge_for_verdict("warn") == (-0.05, -0.05, 0.0)


# AC-62.9
def test_ac_62_9_gate_block_returns_fallback():
    content, was_blocked = gate_through_sentinel("block", "sensitive content")
    assert was_blocked is True
    assert content != "sensitive content"


# AC-62.10
def test_ac_62_10_gate_pass_returns_content():
    content, was_blocked = gate_through_sentinel("pass", "normal content")
    assert content == "normal content"
    assert was_blocked is False
