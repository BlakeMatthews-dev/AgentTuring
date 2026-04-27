"""Tests for specs/conversation-threads.md."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_conversations import (
    AGENT_DAILY_QUOTA,
    ConversationArchived,
    ConversationNotFound,
    CrossUserAccess,
    QuotaExceeded,
    archive_conversation,
    append_message,
    check_quota,
    create_conversation,
    get_conversation,
    get_messages,
    increment_quota,
    verify_conversation_access,
)


NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_SID = "self:test-conv"


@pytest.fixture(autouse=True)
def _create_tables(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS conversations ("
        "conversation_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
        "user_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_messages ("
        "message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, "
        "role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_quotas ("
        "self_id TEXT NOT NULL, user_id TEXT NOT NULL, quota_date TEXT NOT NULL, "
        "count INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (self_id, user_id, quota_date))"
    )


def test_create_conversation(repo):
    conv = create_conversation(repo, _SID, "user-a")
    assert conv["conversation_id"]
    assert conv["user_id"] == "user-a"
    assert conv["status"] == "active"


def test_get_conversation_exists(repo):
    created = create_conversation(repo, _SID, "user-a")
    fetched = get_conversation(repo, created["conversation_id"])
    assert fetched is not None
    assert fetched["user_id"] == "user-a"


def test_get_conversation_not_found(repo):
    assert get_conversation(repo, "nonexistent") is None


def test_append_message(repo):
    conv = create_conversation(repo, _SID, "user-a")
    msg_id = append_message(repo, conv["conversation_id"], "user", "hello")
    assert msg_id


def test_get_messages_ordered(repo):
    conv = create_conversation(repo, _SID, "user-a")
    append_message(repo, conv["conversation_id"], "user", "first")
    append_message(repo, conv["conversation_id"], "assistant", "second")
    msgs = get_messages(repo, conv["conversation_id"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "first"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "second"


def test_get_messages_empty(repo):
    conv = create_conversation(repo, _SID, "user-a")
    assert get_messages(repo, conv["conversation_id"]) == []


def test_archive_conversation(repo):
    conv = create_conversation(repo, _SID, "user-a")
    archive_conversation(repo, conv["conversation_id"])
    fetched = get_conversation(repo, conv["conversation_id"])
    assert fetched["status"] == "archived"


def test_verify_access_success(repo):
    conv = create_conversation(repo, _SID, "user-a")
    result = verify_conversation_access(repo, conv["conversation_id"], "user-a")
    assert result["user_id"] == "user-a"


def test_verify_access_not_found(repo):
    with pytest.raises(ConversationNotFound):
        verify_conversation_access(repo, "nonexistent", "user-a")


def test_verify_access_cross_user(repo):
    conv = create_conversation(repo, _SID, "user-a")
    with pytest.raises(CrossUserAccess):
        verify_conversation_access(repo, conv["conversation_id"], "user-b")


def test_verify_access_archived(repo):
    conv = create_conversation(repo, _SID, "user-a")
    archive_conversation(repo, conv["conversation_id"])
    with pytest.raises(ConversationArchived):
        verify_conversation_access(repo, conv["conversation_id"], "user-a")


def test_check_quota_below(repo):
    assert check_quota(repo, _SID, "user-a", NOW)


def test_check_quota_at_limit(repo):
    increment_quota(repo, _SID, "user-a")
    assert not check_quota(repo, _SID, "user-a", NOW)


def test_check_quota_different_user_independent(repo):
    increment_quota(repo, _SID, "user-a")
    assert check_quota(repo, _SID, "user-b", NOW)


def test_increment_quota_idempotent(repo):
    increment_quota(repo, _SID, "user-a")
    increment_quota(repo, _SID, "user-a")
    row = repo.conn.execute(
        "SELECT count FROM conversation_quotas WHERE self_id = ? AND user_id = ?",
        (_SID, "user-a"),
    ).fetchone()
    assert row[0] == 2


def test_agent_daily_quota_is_one():
    assert AGENT_DAILY_QUOTA == 1
