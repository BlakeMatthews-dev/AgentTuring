"""Prompt management types: diff lines and approval requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ApprovalRequest:
    """A request to promote a prompt version to production."""

    prompt_name: str
    version: int
    requested_by: str
    notes: str = ""
    status: str = "pending"  # pending, approved, rejected
    reviewed_by: str = ""
    review_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = None
