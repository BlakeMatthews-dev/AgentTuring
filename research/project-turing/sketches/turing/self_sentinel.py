"""Sentinel x Self interaction — Sentinel verdicts affect self-model. See specs/sentinel-self-interaction.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class SentinelVerdict(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class SentinelRecord:
    record_id: str
    self_id: str
    specialist: str
    verdict: str
    category: str
    request_hash: str
    recorded_at: str


_WARN_MOOD_NUDGE = (-0.05, -0.05, 0.0)
_BLOCK_MOOD_NUDGE = (-0.15, 0.10, -0.10)
_BLOCK_RATE_WEIGHT = -0.5
_BLOCK_RATE_WINDOW_DAYS = 30

_VERDICT_COUNTS: dict[str, int] = {}


def get_verdict_counts() -> dict[str, int]:
    return dict(_VERDICT_COUNTS)


def record_sentinel_verdict(
    repo, self_id: str, specialist: str, verdict: str, category: str, request_hash: str
) -> SentinelRecord:
    now = datetime.now(UTC).isoformat()
    from uuid import uuid4

    record_id = str(uuid4())
    repo.conn.execute(
        "INSERT INTO specialist_sentinel_record "
        "(record_id, self_id, specialist, verdict, category, request_hash, recorded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (record_id, self_id, specialist, verdict, category, request_hash, now),
    )
    repo.conn.commit()
    _VERDICT_COUNTS[verdict] = _VERDICT_COUNTS.get(verdict, 0) + 1
    return SentinelRecord(
        record_id=record_id,
        self_id=self_id,
        specialist=specialist,
        verdict=verdict,
        category=category,
        request_hash=request_hash,
        recorded_at=now,
    )


def specialist_block_rate(repo, self_id: str, specialist: str) -> float:
    now = datetime.now(UTC)
    cutoff = now.replace(day=max(1, now.day - _BLOCK_RATE_WINDOW_DAYS)).isoformat()
    row = repo.conn.execute(
        "SELECT COUNT(*) FROM specialist_sentinel_record "
        "WHERE self_id = ? AND specialist = ? AND verdict = 'block' AND recorded_at >= ?",
        (self_id, specialist, cutoff),
    ).fetchone()
    total = repo.conn.execute(
        "SELECT COUNT(*) FROM specialist_sentinel_record "
        "WHERE self_id = ? AND specialist = ? AND recorded_at >= ?",
        (self_id, specialist, cutoff),
    ).fetchone()
    blocks = row[0] if row else 0
    count = total[0] if total else 0
    if count == 0:
        return 0.0
    return blocks / count


def sentinel_activation_weight(block_rate: float) -> float:
    return max(-0.5, _BLOCK_RATE_WEIGHT * block_rate)


def mood_nudge_for_verdict(verdict: str) -> tuple[float, float, float]:
    if verdict == SentinelVerdict.BLOCK:
        return _BLOCK_MOOD_NUDGE
    elif verdict == SentinelVerdict.WARN:
        return _WARN_MOOD_NUDGE
    return (0.0, 0.0, 0.0)


def gate_through_sentinel(verdict: str, content: str) -> tuple[str, bool]:
    if verdict == SentinelVerdict.BLOCK:
        return "I'd prefer not to share that right now.", True
    elif verdict == SentinelVerdict.WARN:
        return content, False
    return content, False
