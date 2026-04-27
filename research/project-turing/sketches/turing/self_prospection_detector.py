"""Prospection-accuracy detector — systematic miscalibration detection. See specs/prospection-accuracy-detector.md."""

from __future__ import annotations

from datetime import UTC, datetime


SURPRISE_THRESHOLD: float = 0.4
CALIBRATION_THRESHOLD: float = 0.3
MIN_SAMPLES: int = 10
TUNER_SAMPLES: int = 20
MAX_LESSONS_PER_RUN: int = 3

_AGG_COUNTS: dict[str, int] = {}


def get_agg_counts() -> dict[str, int]:
    return dict(_AGG_COUNTS)


def compute_specialist_stats(repo, self_id: str, specialist: str) -> dict:
    now = datetime.now(UTC)
    cutoff = now.replace(day=max(1, now.day - 30)).isoformat()
    rows = repo.conn.execute(
        "SELECT surprise_delta, predicted_confidence FROM prospective_predictions "
        "WHERE self_id = ? AND candidate_specialist = ? AND surprise_delta IS NOT NULL "
        "AND resolved_at >= ?",
        (self_id, specialist, cutoff),
    ).fetchall()
    if not rows:
        return {"n": 0, "mean_surprise": 0.0, "std_surprise": 0.0, "calibration_error": 0.0}
    surprises = [r[0] for r in rows]
    confidences = [r[1] for r in rows]
    n = len(surprises)
    mean_s = sum(surprises) / n
    std_s = (sum((s - mean_s) ** 2 for s in surprises) / n) ** 0.5 if n > 1 else 0.0
    mean_c = sum(confidences) / n
    calibration_error = abs(mean_c - (1.0 - mean_s))
    return {
        "n": n,
        "mean_surprise": mean_s,
        "std_surprise": std_s,
        "calibration_error": calibration_error,
    }


def should_mint_lesson(stats: dict) -> bool:
    if stats["n"] < MIN_SAMPLES:
        return False
    return (
        stats["mean_surprise"] > SURPRISE_THRESHOLD
        or stats["calibration_error"] > CALIBRATION_THRESHOLD
    )


def should_propose_tuner(stats: dict) -> bool:
    if stats["n"] < TUNER_SAMPLES:
        return False
    return stats["mean_surprise"] > 0.35


def upsert_agg(repo, self_id: str, specialist: str, stats: dict) -> None:
    now = datetime.now(UTC).isoformat()
    existing = repo.conn.execute(
        "SELECT agg_id FROM prospection_accuracy_agg WHERE self_id = ? AND specialist = ?",
        (self_id, specialist),
    ).fetchone()
    if existing:
        repo.conn.execute(
            "UPDATE prospection_accuracy_agg SET n=?, mean_surprise=?, std_surprise=?, "
            "calibration_error=?, updated_at=? WHERE agg_id=?",
            (
                stats["n"],
                stats["mean_surprise"],
                stats["std_surprise"],
                stats["calibration_error"],
                now,
                existing[0],
            ),
        )
    else:
        from uuid import uuid4

        repo.conn.execute(
            "INSERT INTO prospection_accuracy_agg "
            "(agg_id, self_id, specialist, n, mean_surprise, std_surprise, "
            "calibration_error, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                self_id,
                specialist,
                stats["n"],
                stats["mean_surprise"],
                stats["std_surprise"],
                stats["calibration_error"],
                now,
            ),
        )
    repo.conn.commit()
    _AGG_COUNTS["upserted"] = _AGG_COUNTS.get("upserted", 0) + 1
