"""Conversation threads — stateful multi-turn conversations. See specs/conversation-threads.md."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


class ConversationArchived(Exception):
    pass


class ConversationNotFound(Exception):
    pass


class CrossUserAccess(Exception):
    pass


class QuotaExceeded(Exception):
    pass


AGENT_DAILY_QUOTA: int = 1
AUTO_ARCHIVE_DAYS: int = 7


def create_conversation(repo, self_id: str, user_id: str) -> dict:
    conv_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO conversations (conversation_id, self_id, user_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?)",
        (conv_id, self_id, user_id, now, now),
    )
    repo.conn.commit()
    return {"conversation_id": conv_id, "user_id": user_id, "status": "active"}


def get_conversation(repo, conversation_id: str) -> dict | None:
    row = repo.conn.execute(
        "SELECT conversation_id, self_id, user_id, status, created_at FROM conversations "
        "WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "conversation_id": row[0],
        "self_id": row[1],
        "user_id": row[2],
        "status": row[3],
        "created_at": row[4],
    }


def append_message(repo, conversation_id: str, role: str, content: str) -> str:
    msg_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO conversation_messages "
        "(message_id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
        (msg_id, conversation_id, role, content, now),
    )
    repo.conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
        (now, conversation_id),
    )
    repo.conn.commit()
    return msg_id


def get_messages(repo, conversation_id: str) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT message_id, role, content, created_at FROM conversation_messages "
        "WHERE conversation_id = ? ORDER BY created_at",
        (conversation_id,),
    ).fetchall()
    return [{"message_id": r[0], "role": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def archive_conversation(repo, conversation_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "UPDATE conversations SET status = 'archived', updated_at = ? WHERE conversation_id = ?",
        (now, conversation_id),
    )
    repo.conn.commit()


def check_quota(repo, self_id: str, user_id: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    row = repo.conn.execute(
        "SELECT count FROM conversation_quotas WHERE self_id = ? AND user_id = ? AND quota_date = ?",
        (self_id, user_id, date_str),
    ).fetchone()
    used = row[0] if row else 0
    return used < AGENT_DAILY_QUOTA


def increment_quota(repo, self_id: str, user_id: str) -> None:
    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    existing = repo.conn.execute(
        "SELECT count FROM conversation_quotas WHERE self_id = ? AND user_id = ? AND quota_date = ?",
        (self_id, user_id, date_str),
    ).fetchone()
    if existing:
        repo.conn.execute(
            "UPDATE conversation_quotas SET count = count + 1 WHERE self_id = ? AND user_id = ? AND quota_date = ?",
            (self_id, user_id, date_str),
        )
    else:
        repo.conn.execute(
            "INSERT INTO conversation_quotas (self_id, user_id, quota_date, count) VALUES (?,?,?,1)",
            (self_id, user_id, date_str),
        )
    repo.conn.commit()


def verify_conversation_access(repo, conversation_id: str, user_id: str) -> dict:
    conv = get_conversation(repo, conversation_id)
    if conv is None:
        raise ConversationNotFound(conversation_id)
    if conv["user_id"] != user_id:
        raise CrossUserAccess(f"user {user_id} cannot access conversation {conversation_id}")
    if conv["status"] == "archived":
        raise ConversationArchived(conversation_id)
    return conv
