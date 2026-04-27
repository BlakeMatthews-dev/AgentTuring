"""Self-naming ritual — self-initiated naming. See specs/self-naming-ritual.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

NAME_PATTERN = re.compile(r"^[A-Z][a-z]{1,15}(-[A-Z][a-z]{1,15})?$")
DURABLE_MEMORY_THRESHOLD: int = 1000
NAMING_COOLDOWN_DAYS: int = 90


@dataclass
class NameProposal:
    proposal_id: str
    self_id: str
    proposed_name: str
    rationale: str
    status: str
    proposed_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None


class InvalidName(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"invalid name: {name!r}")


def validate_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name))


def naming_trigger_check(repo, self_id: str) -> bool:
    current_name = repo.conn.execute(
        "SELECT display_name FROM self_identity WHERE self_id = ?",
        (self_id,),
    ).fetchone()
    if current_name and current_name[0]:
        return False
    pending = repo.conn.execute(
        "SELECT COUNT(*) FROM self_name_proposals WHERE self_id = ? AND status = 'pending'",
        (self_id,),
    ).fetchone()[0]
    if pending > 0:
        return False
    durable_count = repo.conn.execute(
        "SELECT COUNT(*) FROM durable_memory WHERE self_id = ?",
        (self_id,),
    ).fetchone()[0]
    return durable_count >= DURABLE_MEMORY_THRESHOLD


def insert_proposal(repo, proposal: NameProposal) -> None:
    repo.conn.execute(
        "INSERT INTO self_name_proposals "
        "(proposal_id, self_id, proposed_name, rationale, status, proposed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            proposal.proposal_id,
            proposal.self_id,
            proposal.proposed_name,
            proposal.rationale,
            proposal.status,
            proposal.proposed_at,
        ),
    )
    repo.conn.commit()


def ack_name(
    repo, proposal_id: str, decision: str, reviewed_by: str, alternative: str | None = None
) -> None:
    now = datetime.now(UTC).isoformat()
    final_name = alternative if decision == "approve" and alternative else None
    row = repo.conn.execute(
        "SELECT self_id, proposed_name FROM self_name_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no proposal with id={proposal_id}")
    self_id, proposed_name = row[0], row[1]
    repo.conn.execute(
        "UPDATE self_name_proposals SET status = ?, reviewed_by = ?, reviewed_at = ? "
        "WHERE proposal_id = ?",
        (decision, reviewed_by, now, proposal_id),
    )
    if decision == "approve":
        name = final_name or proposed_name
        repo.conn.execute(
            "UPDATE self_identity SET display_name = ?, named_at = ?, naming_source = 'ritual' "
            "WHERE self_id = ?",
            (name, now, self_id),
        )
    repo.conn.commit()
