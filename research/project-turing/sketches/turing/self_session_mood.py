"""Session-scoped mood — per-conversation sub-mood. See specs/session-scoped-mood.md."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ConversationMood:
    conversation_id: str
    self_id: str
    valence: float = 0.0
    arousal: float = 0.3
    focus: float = 0.5
    last_tick_at: str = ""
    archived: bool = False


SESSION_DECAY_RATE: float = 0.3
SESSION_MERGE_THRESHOLD: float = 0.3

_conversation_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_conversation_id", default=None
)


def get_conversation_id() -> str | None:
    return _conversation_var.get()


class conversation_scope:
    def __init__(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        self._token = None

    def __enter__(self):
        self._token = _conversation_var.set(self._conversation_id)
        return self

    def __exit__(self, *args):
        _conversation_var.reset(self._token)


class NoActiveConversation(Exception):
    pass


def create_conversation_mood(repo, conversation_id: str, self_id: str) -> ConversationMood:
    now = datetime.now(UTC).isoformat()
    global_mood = repo.conn.execute(
        "SELECT valence, arousal, focus FROM self_mood WHERE self_id = ?",
        (self_id,),
    ).fetchone()
    v, a, f = 0.0, 0.3, 0.5
    if global_mood:
        v, a, f = global_mood[0], global_mood[1], global_mood[2]
    repo.conn.execute(
        "INSERT INTO conversation_mood (conversation_id, self_id, valence, arousal, focus, last_tick_at, archived) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (conversation_id, self_id, v, a, f, now),
    )
    repo.conn.commit()
    return ConversationMood(
        conversation_id=conversation_id,
        self_id=self_id,
        valence=v,
        arousal=a,
        focus=f,
        last_tick_at=now,
    )


def get_conversation_mood(repo, conversation_id: str) -> ConversationMood | None:
    row = repo.conn.execute(
        "SELECT conversation_id, self_id, valence, arousal, focus, last_tick_at, archived "
        "FROM conversation_mood WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return ConversationMood(
        conversation_id=row[0],
        self_id=row[1],
        valence=row[2],
        arousal=row[3],
        focus=row[4],
        last_tick_at=row[5],
        archived=bool(row[6]),
    )


def nudge_session_mood(
    repo, conversation_id: str, dv: float, da: float, df: float
) -> ConversationMood | None:
    cm = get_conversation_mood(repo, conversation_id)
    if cm is None or cm.archived:
        return None
    cm.valence = max(-1.0, min(1.0, cm.valence + dv))
    cm.arousal = max(0.0, min(1.0, cm.arousal + da))
    cm.focus = max(0.0, min(1.0, cm.focus + df))
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "UPDATE conversation_mood SET valence=?, arousal=?, focus=?, last_tick_at=? WHERE conversation_id=?",
        (cm.valence, cm.arousal, cm.focus, now, conversation_id),
    )
    repo.conn.commit()
    return cm


def archive_conversation_mood(repo, conversation_id: str) -> None:
    repo.conn.execute(
        "UPDATE conversation_mood SET archived=1 WHERE conversation_id=?",
        (conversation_id,),
    )
    repo.conn.commit()
