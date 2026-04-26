"""Tests for turing.self_session_mood: conversation-scoped mood."""

from __future__ import annotations

import pytest

from turing.self_session_mood import (
    NoActiveConversation,
    archive_conversation_mood,
    conversation_scope,
    create_conversation_mood,
    get_conversation_id,
    get_conversation_mood,
    nudge_session_mood,
)


@pytest.fixture(autouse=True)
def _create_conversation_mood_table(repo):
    repo.conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_mood ("
        "conversation_id TEXT PRIMARY KEY,"
        "self_id TEXT NOT NULL,"
        "valence REAL NOT NULL,"
        "arousal REAL NOT NULL,"
        "focus REAL NOT NULL,"
        "last_tick_at TEXT NOT NULL,"
        "archived INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    repo.conn.commit()


def test_get_conversation_id_returns_none_outside_scope() -> None:
    assert get_conversation_id() is None


def test_conversation_scope_sets_id_inside_and_restores_after() -> None:
    assert get_conversation_id() is None
    with conversation_scope("conv-1"):
        assert get_conversation_id() == "conv-1"
    assert get_conversation_id() is None


def test_create_conversation_mood_inherits_global_values(repo, bootstrapped_id) -> None:
    cid = "conv-inherit"
    cm = create_conversation_mood(repo, cid, bootstrapped_id)
    assert cm is not None
    assert cm.conversation_id == cid
    assert cm.self_id == bootstrapped_id
    assert cm.valence == pytest.approx(0.0)
    assert cm.arousal == pytest.approx(0.3)
    assert cm.focus == pytest.approx(0.5)
    assert cm.archived is False


def test_get_conversation_mood_returns_none_for_unknown(repo) -> None:
    assert get_conversation_mood(repo, "no-such-conv") is None


def test_nudge_session_mood_updates_values(repo, bootstrapped_id) -> None:
    cid = "conv-nudge"
    create_conversation_mood(repo, cid, bootstrapped_id)
    cm = nudge_session_mood(repo, cid, dv=0.2, da=-0.1, df=0.15)
    assert cm is not None
    assert cm.valence == pytest.approx(0.2)
    assert cm.arousal == pytest.approx(0.2)
    assert cm.focus == pytest.approx(0.65)


def test_archive_conversation_mood_sets_archived(repo, bootstrapped_id) -> None:
    cid = "conv-archive"
    create_conversation_mood(repo, cid, bootstrapped_id)
    archive_conversation_mood(repo, cid)
    cm = get_conversation_mood(repo, cid)
    assert cm is not None
    assert cm.archived is True


def test_nudge_on_archived_returns_none(repo, bootstrapped_id) -> None:
    cid = "conv-archived-nudge"
    create_conversation_mood(repo, cid, bootstrapped_id)
    archive_conversation_mood(repo, cid)
    result = nudge_session_mood(repo, cid, dv=0.1, da=0.0, df=0.0)
    assert result is None
