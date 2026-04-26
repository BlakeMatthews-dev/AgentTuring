"""Prospective simulation — predict outcomes before routing. See specs/prospective-simulation.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass
class Prediction:
    prediction_id: str
    self_id: str
    request_hash: str
    candidate_specialist: str
    predicted_outcome_summary: str
    predicted_confidence: float
    chosen: bool = False
    actual_outcome: str | None = None
    surprise_delta: float | None = None
    resolved_at: str | None = None


PROSPECTION_MAX_CANDIDATES: int = 3
PROSPECTION_INPUT_BUDGET: int = 1500
PROSPECTION_OUTPUT_BUDGET: int = 200
PROSPECTION_TIMEOUT_SEC: float = 10.0
SURPRISE_THRESHOLD_LESSON: float = 0.5
SURPRISE_THRESHOLD_QUIET: float = 0.15

_TIMEOUT_COUNTS: int = 0


def get_timeout_count() -> int:
    return _TIMEOUT_COUNTS


def create_prediction(
    repo,
    self_id: str,
    request_hash: str,
    candidate_specialist: str,
    predicted_summary: str,
    confidence: float,
) -> Prediction:
    pred_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO prospective_predictions "
        "(prediction_id, self_id, request_hash, candidate_specialist, "
        "predicted_outcome_summary, predicted_confidence, chosen, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (pred_id, self_id, request_hash, candidate_specialist, predicted_summary, confidence, now),
    )
    repo.conn.commit()
    return Prediction(
        prediction_id=pred_id,
        self_id=self_id,
        request_hash=request_hash,
        candidate_specialist=candidate_specialist,
        predicted_outcome_summary=predicted_summary,
        predicted_confidence=confidence,
    )


def mark_chosen(repo, prediction_id: str) -> None:
    repo.conn.execute(
        "UPDATE prospective_predictions SET chosen = 1 WHERE prediction_id = ?",
        (prediction_id,),
    )
    repo.conn.commit()


def resolve_prediction(
    repo, prediction_id: str, actual_outcome: str, surprise_delta: float
) -> None:
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "UPDATE prospective_predictions SET actual_outcome = ?, surprise_delta = ?, resolved_at = ? "
        "WHERE prediction_id = ?",
        (actual_outcome, surprise_delta, now, prediction_id),
    )
    repo.conn.commit()


def should_mint_lesson(surprise_delta: float) -> bool:
    return surprise_delta >= SURPRISE_THRESHOLD_LESSON


def should_mint_quiet(surprise_delta: float) -> bool:
    return surprise_delta < SURPRISE_THRESHOLD_QUIET
