"""Stable self_id minting and bootstrap. See specs/persistence.md §8.2."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4


def bootstrap_self_id(conn: sqlite3.Connection) -> str:
    """Read the active self_id; mint one if none exists.

    Exactly one row in `self_identity` has `archived_at IS NULL`.
    """
    cur = conn.execute(
        "SELECT self_id FROM self_identity WHERE archived_at IS NULL LIMIT 1"
    )
    row = cur.fetchone()
    if row is not None:
        return row[0]

    new_id = str(uuid4())
    conn.execute(
        "INSERT INTO self_identity (self_id, created_at) VALUES (?, ?)",
        (new_id, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    return new_id


def archive_and_mint_new(conn: sqlite3.Connection, reason: str) -> str:
    """Archive the active self_id and mint a new one.

    Operator-initiated (clean-slate bootstrap). The old row stays readable
    with its `archived_at` and `archive_reason` populated.
    """
    now_iso = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE self_identity "
        "SET archived_at = ?, archive_reason = ? "
        "WHERE archived_at IS NULL",
        (now_iso, reason),
    )
    new_id = str(uuid4())
    conn.execute(
        "INSERT INTO self_identity (self_id, created_at) VALUES (?, ?)",
        (new_id, now_iso),
    )
    conn.commit()
    return new_id
