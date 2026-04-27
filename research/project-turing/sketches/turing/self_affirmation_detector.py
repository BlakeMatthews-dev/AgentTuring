"""Affirmation-candidacy detector — consistently-succeeding routing patterns. See specs/affirmation-candidacy-detector.md."""

from __future__ import annotations

from datetime import UTC, datetime


MIN_HITS: int = 7
MIN_SUCCESS_RATE: float = 0.85
REJECTION_COOLDOWN_DAYS: int = 30
APPROVED_CONTRIBUTOR_WEIGHT: float = 0.3

_CANDIDATE_COUNTS: dict[str, int] = {}


def get_candidate_counts() -> dict[str, int]:
    return dict(_CANDIDATE_COUNTS)


def compute_success_rates(repo, self_id: str, now: datetime) -> list[dict]:
    cutoff = now.replace(day=max(1, now.day - 30)).isoformat() if hasattr(now, "isoformat") else now
    rows = repo.conn.execute(
        "SELECT context FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'route request' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 200",
        (self_id, cutoff),
    ).fetchall()
    import json

    specialist_stats: dict[str, dict[str, int]] = {}
    for row in rows:
        ctx = json.loads(row[0]) if row[0] and isinstance(row[0], str) else (row[0] or {})
        specialist = ctx.get("decision", "unknown")
        outcome = ctx.get("outcome", "ok")
        if specialist not in specialist_stats:
            specialist_stats[specialist] = {"total": 0, "success": 0}
        specialist_stats[specialist]["total"] += 1
        if outcome in ("ok", "reply_directly", "delegate"):
            specialist_stats[specialist]["success"] += 1
    results = []
    for specialist, stats in specialist_stats.items():
        rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0.0
        results.append(
            {
                "specialist": specialist,
                "hits": stats["total"],
                "success_rate": rate,
            }
        )
    return results


def qualifies_as_candidate(entry: dict) -> bool:
    return entry["hits"] >= MIN_HITS and entry["success_rate"] >= MIN_SUCCESS_RATE


def insert_candidate(repo, self_id: str, specialist: str, success_rate: float, hits: int) -> str:
    from uuid import uuid4

    cid = str(uuid4())
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO affirmation_candidates "
        "(candidate_id, self_id, specialist, success_rate, hits, status, detected_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (cid, self_id, specialist, success_rate, hits, now),
    )
    repo.conn.commit()
    _CANDIDATE_COUNTS["inserted"] = _CANDIDATE_COUNTS.get("inserted", 0) + 1
    return cid


def ack_candidate(repo, candidate_id: str, decision: str, reviewed_by: str) -> None:
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "UPDATE affirmation_candidates SET status = ?, reviewed_by = ?, reviewed_at = ? "
        "WHERE candidate_id = ?",
        (decision, reviewed_by, now, candidate_id),
    )
    repo.conn.commit()
    _CANDIDATE_COUNTS[decision] = _CANDIDATE_COUNTS.get(decision, 0) + 1
