"""Learning-extraction detector — pairs REGRET→later-success patterns. See specs/learning-extraction-detector.md."""

from __future__ import annotations

from datetime import UTC, datetime


SIMILARITY_THRESHOLD: float = 0.75
PROMOTION_HITS: int = 3
COALESCE_WINDOW_DAYS: int = 14

_DETECTION_COUNTS: dict[str, int] = {}


def get_detection_counts() -> dict[str, int]:
    return dict(_DETECTION_COUNTS)


def find_regret_success_pairs(repo, self_id: str, now: datetime) -> list[dict]:
    regrets = repo.conn.execute(
        "SELECT memory_id, content, context FROM durable_memory "
        "WHERE self_id = ? AND tier = 'regret' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 50",
        (
            self_id,
            (
                now.replace(day=max(1, now.day - 30)).isoformat()
                if hasattr(now, "isoformat")
                else now
            ),
        ),
    ).fetchall()
    successes = repo.conn.execute(
        "SELECT memory_id, content, context FROM durable_memory "
        "WHERE self_id = ? AND tier = 'affirmation' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 50",
        (
            self_id,
            (
                now.replace(day=max(1, now.day - 30)).isoformat()
                if hasattr(now, "isoformat")
                else now
            ),
        ),
    ).fetchall()
    pairs = []
    for r in regrets:
        for s in successes:
            pairs.append(
                {
                    "regret_id": r[0],
                    "regret_content": r[1],
                    "success_id": s[0],
                    "success_content": s[1],
                }
            )
    _DETECTION_COUNTS["pairs"] = _DETECTION_COUNTS.get("pairs", 0) + len(pairs)
    return pairs


def coalesce_or_insert_candidate(
    repo, self_id: str, failed_specialist: str, succeeded_specialist: str, similarity: float
) -> str:
    existing = repo.conn.execute(
        "SELECT candidate_id, hits FROM learning_candidates "
        "WHERE self_id = ? AND failed_specialist = ? AND succeeded_specialist = ? "
        "AND promoted_at IS NULL AND detected_at >= ?",
        (
            self_id,
            failed_specialist,
            succeeded_specialist,
            datetime.now(UTC)
            .replace(day=max(1, datetime.now(UTC).day - COALESCE_WINDOW_DAYS))
            .isoformat(),
        ),
    ).fetchone()
    if existing:
        repo.conn.execute(
            "UPDATE learning_candidates SET hits = hits + 1 WHERE candidate_id = ?",
            (existing[0],),
        )
        repo.conn.commit()
        return existing[0]
    from uuid import uuid4

    cid = str(uuid4())
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO learning_candidates "
        "(candidate_id, self_id, failed_specialist, succeeded_specialist, similarity, hits, detected_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (cid, self_id, failed_specialist, succeeded_specialist, similarity, now),
    )
    repo.conn.commit()
    return cid


def check_promotion(repo, candidate_id: str) -> bool:
    row = repo.conn.execute(
        "SELECT hits FROM learning_candidates WHERE candidate_id = ? AND promoted_at IS NULL",
        (candidate_id,),
    ).fetchone()
    if row and row[0] >= PROMOTION_HITS:
        return True
    return False


def promote_candidate(repo, candidate_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "UPDATE learning_candidates SET promoted_at = ? WHERE candidate_id = ?",
        (now, candidate_id),
    )
    repo.conn.commit()
    _DETECTION_COUNTS["promoted"] = _DETECTION_COUNTS.get("promoted", 0) + 1
