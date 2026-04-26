"""Human feedback reward system.

Points motivate the agent. Every interface where the agent creates content
that a human can see earns points:

    Chat:    creation=5, thumbs_up=10, thumbs_down=-20
    Default: creation=5, thumbs_up=100, thumbs_down=-200

Reward totals feed back into the motivation pressure vector so the agent
learns which interfaces and content styles earn the most approval.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4


REWARD_SCHEDULE: dict[str, dict[str, int]] = {
    "chat": {"creation": 5, "thumbs_up": 10, "thumbs_down": -20},
    "blog": {"creation": 5, "thumbs_up": 100, "thumbs_down": -200},
    "hobby": {"creation": 5, "thumbs_up": 100, "thumbs_down": -200},
    "curiosity": {"creation": 5, "thumbs_up": 100, "thumbs_down": -200},
}

DEFAULT_SCHEDULE: dict[str, int] = {"creation": 5, "thumbs_up": 100, "thumbs_down": -200}

_VALID_EVENTS = {"creation", "thumbs_up", "thumbs_down"}


class RewardTracker:
    def __init__(self, conn: sqlite3.Connection, self_id: str) -> None:
        self._conn = conn
        self._self_id = self_id

    def _ensure_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reward_events (
                event_id    TEXT PRIMARY KEY,
                self_id     TEXT NOT NULL,
                interface   TEXT NOT NULL,
                item_id     TEXT NOT NULL,
                event_type  TEXT NOT NULL CHECK (event_type IN ('creation', 'thumbs_up', 'thumbs_down')),
                points      INTEGER NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reward_events_self ON reward_events (self_id, created_at DESC)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reward_events_item ON reward_events (item_id, event_type)"
        )
        self._conn.commit()

    def award(
        self,
        *,
        interface: str,
        item_id: str,
        event_type: str,
    ) -> int:
        if event_type not in _VALID_EVENTS:
            raise ValueError(f"invalid event_type: {event_type!r}")
        schedule = REWARD_SCHEDULE.get(interface, DEFAULT_SCHEDULE)
        points = schedule.get(event_type, 0)
        if points == 0:
            return 0
        event_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        self._ensure_table()
        self._conn.execute(
            "INSERT INTO reward_events (event_id, self_id, interface, item_id, event_type, points, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, self._self_id, interface, item_id, event_type, points, now),
        )
        self._conn.commit()
        return points

    def total_points(self) -> int:
        self._ensure_table()
        row = self._conn.execute(
            "SELECT COALESCE(SUM(points), 0) FROM reward_events WHERE self_id = ?",
            (self._self_id,),
        ).fetchone()
        return int(row[0])

    def points_by_interface(self) -> dict[str, int]:
        self._ensure_table()
        rows = self._conn.execute(
            "SELECT interface, COALESCE(SUM(points), 0) FROM reward_events WHERE self_id = ? GROUP BY interface",
            (self._self_id,),
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def has_feedback(self, item_id: str) -> bool:
        self._ensure_table()
        row = self._conn.execute(
            "SELECT COUNT(*) FROM reward_events WHERE item_id = ? AND event_type IN ('thumbs_up', 'thumbs_down')",
            (item_id,),
        ).fetchone()
        return int(row[0]) > 0

    def recent_events(self, limit: int = 20) -> list[dict]:
        self._ensure_table()
        rows = self._conn.execute(
            "SELECT event_id, interface, item_id, event_type, points, created_at "
            "FROM reward_events WHERE self_id = ? ORDER BY created_at DESC LIMIT ?",
            (self._self_id, limit),
        ).fetchall()
        return [
            {
                "event_id": r[0],
                "interface": r[1],
                "item_id": r[2],
                "event_type": r[3],
                "points": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
