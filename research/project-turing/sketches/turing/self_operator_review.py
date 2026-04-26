"""Operator review gate for self-authored contributors. See specs/operator-review-gate.md."""

from __future__ import annotations

from datetime import UTC, datetime

from .self_model import NodeKind


PENDING_MAX_AGE_DAYS: int = 30

_GATED_KINDS = frozenset({NodeKind.PERSONALITY_FACET, NodeKind.PASSION})


def is_gated_target(target_kind: NodeKind | str) -> bool:
    return target_kind in _GATED_KINDS


def insert_pending_contributor(repo, contributor, *, acting_self_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    repo.conn.execute(
        "INSERT INTO self_contributor_pending "
        "(node_id, self_id, target_node_id, target_kind, source_id, source_kind, "
        "weight, origin, rationale, expires_at, proposed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            contributor.node_id,
            contributor.self_id,
            contributor.target_node_id,
            contributor.target_kind.value
            if hasattr(contributor.target_kind, "value")
            else contributor.target_kind,
            contributor.source_id,
            contributor.source_kind,
            contributor.weight,
            contributor.origin.value,
            contributor.rationale,
            contributor.expires_at.isoformat() if contributor.expires_at else None,
            now,
        ),
    )
    repo.conn.commit()


def ack_pending(repo, node_id: str, decision: str, reviewed_by: str) -> None:
    now = datetime.now(UTC).isoformat()
    row = repo.conn.execute(
        "SELECT node_id, self_id, target_node_id, target_kind, source_id, source_kind, "
        "weight, origin, rationale, expires_at FROM self_contributor_pending WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no pending contributor with node_id={node_id}")
    repo.conn.execute(
        "UPDATE self_contributor_pending SET review_decision = ?, reviewed_by = ?, reviewed_at = ? "
        "WHERE node_id = ?",
        (decision, reviewed_by, now, node_id),
    )
    if decision == "approve":
        repo.conn.execute(
            "INSERT INTO self_activation_contributors "
            "(node_id, self_id, target_node_id, target_kind, source_id, source_kind, "
            "weight, origin, rationale, expires_at, retracted_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                None,
                now,
                now,
            ),
        )
    repo.conn.commit()


def list_pending(repo, self_id: str) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT node_id, target_node_id, target_kind, source_id, weight, proposed_at "
        "FROM self_contributor_pending WHERE self_id = ? AND review_decision IS NULL",
        (self_id,),
    ).fetchall()
    return [
        {
            "node_id": r[0],
            "target_node_id": r[1],
            "target_kind": r[2],
            "source_id": r[3],
            "weight": r[4],
            "proposed_at": r[5],
        }
        for r in rows
    ]
