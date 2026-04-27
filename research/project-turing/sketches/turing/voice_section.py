"""VoiceSection: the self-owned text block that describes how Turing sounds.

A single string per self_id, persisted in the `voice_section` table.
Starts empty — Turing earns its voice by writing it over time via the
voice_section_maintenance loop. The operator can seed an initial value
via the `voice_section_path` config option (loaded once on first boot
when the DB row is missing; thereafter the self controls it).

Modeled on working_memory.py but simpler: one row, one string, one cap.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


DEFAULT_MAX_CHARS: int = 600


class VoiceSection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_section (
                self_id     TEXT PRIMARY KEY,
                content     TEXT NOT NULL DEFAULT '',
                max_chars   INTEGER NOT NULL DEFAULT 600,
                updated_at  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, self_id: str) -> str:
        row = self._conn.execute(
            "SELECT content FROM voice_section WHERE self_id = ?", (self_id,)
        ).fetchone()
        return row[0] if row else ""

    def set(self, self_id: str, content: str, now: datetime | None = None) -> None:
        """Write voice content, capped to max_chars."""
        max_chars = self._get_max_chars(self_id)
        content = (content or "").strip()[:max_chars]
        ts = (now or datetime.now(UTC)).isoformat()
        self._conn.execute(
            """
            INSERT INTO voice_section (self_id, content, max_chars, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (self_id) DO UPDATE
                SET content = excluded.content,
                    updated_at = excluded.updated_at
            """,
            (self_id, content, max_chars, ts),
        )
        self._conn.commit()

    def seed_if_empty(self, self_id: str, content: str, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        """Set the voice section only if it has never been written (first boot)."""
        existing = self.get(self_id)
        if existing:
            return
        content = (content or "").strip()[:max_chars]
        if not content:
            return
        ts = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO voice_section (self_id, content, max_chars, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (self_id) DO NOTHING
            """,
            (self_id, content, max_chars, ts),
        )
        self._conn.commit()

    def clear(self, self_id: str) -> None:
        self._conn.execute(
            "UPDATE voice_section SET content = '', updated_at = ? WHERE self_id = ?",
            (datetime.now(UTC).isoformat(), self_id),
        )
        self._conn.commit()

    def _get_max_chars(self, self_id: str) -> int:
        row = self._conn.execute(
            "SELECT max_chars FROM voice_section WHERE self_id = ?", (self_id,)
        ).fetchone()
        return row[0] if row else DEFAULT_MAX_CHARS
