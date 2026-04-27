"""Operator coaching channel — one-way operator→self teaching. See specs/operator-coaching-channel.md."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta


COACHING_MOOD_NUDGE = (0.0, 0.0, 0.05)
OVER_COACHING_THRESHOLD: int = 5
OVER_COACHING_WINDOW_HOURS: int = 24


def _signing_key() -> bytes:
    key = os.environ.get("OPERATOR_SIGNING_KEY", "")
    return key.encode()


def sign_coaching(content: str, operator_id: str, created_at: str) -> str:
    canonical = f"{operator_id}|{created_at}|{content}"
    return hmac.new(_signing_key(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_coaching_signature(
    content: str, operator_id: str, created_at: str, signature: str
) -> bool:
    expected = sign_coaching(content, operator_id, created_at)
    return hmac.compare_digest(expected, signature)


def check_over_coaching(repo, self_id: str) -> bool:
    now = datetime.now(UTC)
    cutoff = (now - timedelta(hours=OVER_COACHING_WINDOW_HOURS)).isoformat()
    row = repo.conn.execute(
        "SELECT COUNT(*) FROM self_coaching_log WHERE self_id = ? AND created_at >= ?",
        (self_id, cutoff),
    ).fetchone()
    return (row[0] if row else 0) >= OVER_COACHING_THRESHOLD


def coach_self(
    repo,
    self_id: str,
    *,
    content: str,
    tier: str = "OPINION",
    operator_id: str = "operator",
    skip_mood: bool = False,
) -> str:
    from uuid import uuid4

    now = datetime.now(UTC).isoformat()
    coaching_id = str(uuid4())
    signature = sign_coaching(content, operator_id, now)
    over_coached = check_over_coaching(repo, self_id)
    repo.conn.execute(
        "INSERT INTO self_coaching_log "
        "(coaching_id, self_id, content, tier, operator_id, signature, "
        "over_coached, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (coaching_id, self_id, content, tier, operator_id, signature, int(over_coached), now),
    )
    repo.conn.commit()
    return coaching_id
