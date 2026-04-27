"""Tests for specs/self-naming-ritual.md: AC-61.*."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_naming import (
    DURABLE_MEMORY_THRESHOLD,
    InvalidName,
    NameProposal,
    ack_name,
    insert_proposal,
    naming_trigger_check,
    validate_name,
)


@pytest.fixture(autouse=True)
def _ensure_naming_schema(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS self_name_proposals ("
        "proposal_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "proposed_name TEXT NOT NULL, rationale TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "proposed_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by TEXT)"
    )
    cur = repo.conn.execute("PRAGMA table_info(self_identity)")
    columns = {row[1] for row in cur.fetchall()}
    if "display_name" not in columns:
        repo.conn.execute("ALTER TABLE self_identity ADD COLUMN display_name TEXT")
    if "named_at" not in columns:
        repo.conn.execute("ALTER TABLE self_identity ADD COLUMN named_at TEXT")
    if "naming_source" not in columns:
        repo.conn.execute("ALTER TABLE self_identity ADD COLUMN naming_source TEXT")
    repo.conn.commit()


def _insert_durable(repo, self_id, count):
    now = datetime.now(UTC).isoformat()
    tier = "wisdom"
    for i in range(count):
        repo.conn.execute(
            "INSERT OR IGNORE INTO episodic_memory "
            "(memory_id, self_id, tier, source, content, weight, "
            "affect, confidence_at_creation, surprise_delta, intent_at_time, "
            "created_at, last_accessed_at) "
            "VALUES (?, ?, 'observation', 'i_did', ?, 0.5, 0.0, 0.5, 0.0, '', ?, ?)",
            (f"dur:{i}", self_id, f"durable {i}", now, now),
        )
    repo.conn.execute("DELETE FROM durable_memory WHERE self_id = ?", (self_id,))
    for i in range(count):
        repo.conn.execute(
            "INSERT OR IGNORE INTO durable_memory "
            "(memory_id, self_id, tier, source, content, weight, "
            "affect, confidence_at_creation, surprise_delta, intent_at_time, "
            "origin_episode_id, created_at, last_accessed_at) "
            "VALUES (?, ?, 'regret', 'i_did', ?, 0.5, 0.0, 0.5, 0.0, '', ?, ?, ?)",
            (f"dur-d:{i}", self_id, f"durable {i}", f"dur:{i}", now, now),
        )
    repo.conn.commit()


# AC-61.1
def test_ac_61_1_validate_name_single_word():
    assert validate_name("Aurora") is True


# AC-61.2
def test_ac_61_2_validate_name_lowercase_start():
    assert validate_name("mary") is False


# AC-61.3
def test_ac_61_3_validate_name_too_short():
    assert validate_name("A") is False


# AC-61.4
def test_ac_61_4_validate_name_hyphenated():
    assert validate_name("Fair-Light") is True


# AC-61.5
def test_ac_61_5_trigger_no_display_name_no_durable(repo, self_id):
    assert naming_trigger_check(repo, self_id) is False


# AC-61.6
def test_ac_61_6_trigger_existing_display_name(repo, self_id):
    repo.conn.execute(
        "UPDATE self_identity SET display_name = 'Already' WHERE self_id = ?",
        (self_id,),
    )
    repo.conn.commit()
    _insert_durable(repo, self_id, DURABLE_MEMORY_THRESHOLD)
    assert naming_trigger_check(repo, self_id) is False


# AC-61.7
def test_ac_61_7_insert_proposal_adds_row(repo, self_id, new_id):
    proposal = NameProposal(
        proposal_id=new_id("prop"),
        self_id=self_id,
        proposed_name="Aurora",
        rationale="first light",
        status="pending",
        proposed_at=datetime.now(UTC).isoformat(),
    )
    insert_proposal(repo, proposal)
    row = repo.conn.execute(
        "SELECT proposed_name, status FROM self_name_proposals WHERE proposal_id = ?",
        (proposal.proposal_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "Aurora"
    assert row[1] == "pending"


# AC-61.8
def test_ac_61_8_ack_approve_sets_display_name(repo, self_id, new_id):
    proposal = NameProposal(
        proposal_id=new_id("prop"),
        self_id=self_id,
        proposed_name="Aurora",
        rationale="first light",
        status="pending",
        proposed_at=datetime.now(UTC).isoformat(),
    )
    insert_proposal(repo, proposal)
    ack_name(repo, proposal.proposal_id, "approve", reviewed_by="operator")
    row = repo.conn.execute(
        "SELECT display_name, naming_source FROM self_identity WHERE self_id = ?",
        (self_id,),
    ).fetchone()
    assert row[0] == "Aurora"
    assert row[1] == "ritual"
    prop_row = repo.conn.execute(
        "SELECT status FROM self_name_proposals WHERE proposal_id = ?",
        (proposal.proposal_id,),
    ).fetchone()
    assert prop_row[0] == "approve"
