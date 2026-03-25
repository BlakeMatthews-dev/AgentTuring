"""Learning approval gate.

Learnings that cross the promotion threshold enter 'pending_approval'
status. An admin must approve before they promote to 'promoted' and
trigger skill mutations.

Approval statuses: pending_approval → approved → promoted (+ mutation)
                   pending_approval → rejected
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("stronghold.learnings.approval")


@dataclass
class LearningApproval:
    """An approval request for a learning promotion."""

    learning_id: int
    org_id: str = ""
    status: str = "pending"  # pending, approved, rejected
    requested_at: float = field(default_factory=time.time)
    reviewed_by: str = ""
    reviewed_at: float = 0.0
    review_notes: str = ""
    learning_preview: str = ""
    tool_name: str = ""
    hit_count: int = 0


class LearningApprovalGate:
    """In-memory approval gate for learning promotions."""

    def __init__(self) -> None:
        self._approvals: dict[int, LearningApproval] = {}  # learning_id → approval

    def request_approval(
        self,
        learning_id: int,
        org_id: str = "",
        learning_preview: str = "",
        tool_name: str = "",
        hit_count: int = 0,
    ) -> LearningApproval:
        """Create an approval request for a learning."""
        if learning_id in self._approvals:
            return self._approvals[learning_id]

        approval = LearningApproval(
            learning_id=learning_id,
            org_id=org_id,
            learning_preview=learning_preview,
            tool_name=tool_name,
            hit_count=hit_count,
        )
        self._approvals[learning_id] = approval
        logger.info("Approval requested for learning #%d (org=%s)", learning_id, org_id)
        return approval

    def approve(
        self,
        learning_id: int,
        reviewer: str,
        notes: str = "",
    ) -> LearningApproval | None:
        """Approve a pending learning. Returns updated approval or None."""
        approval = self._approvals.get(learning_id)
        if not approval or approval.status != "pending":
            return None
        approval.status = "approved"
        approval.reviewed_by = reviewer
        approval.reviewed_at = time.time()
        approval.review_notes = notes
        logger.info("Learning #%d approved by %s", learning_id, reviewer)
        return approval

    def reject(
        self,
        learning_id: int,
        reviewer: str,
        reason: str = "",
    ) -> LearningApproval | None:
        """Reject a pending learning."""
        approval = self._approvals.get(learning_id)
        if not approval or approval.status != "pending":
            return None
        approval.status = "rejected"
        approval.reviewed_by = reviewer
        approval.reviewed_at = time.time()
        approval.review_notes = reason
        logger.info("Learning #%d rejected by %s: %s", learning_id, reviewer, reason)
        return approval

    def get_pending(self, org_id: str = "") -> list[LearningApproval]:
        """Get all pending approvals for an org."""
        results = [
            a
            for a in self._approvals.values()
            if a.status == "pending" and (not org_id or a.org_id == org_id)
        ]
        results.sort(key=lambda a: a.requested_at, reverse=True)
        return results

    def get_approved_ids(self) -> list[int]:
        """Get learning IDs that have been approved (ready for promotion)."""
        return [a.learning_id for a in self._approvals.values() if a.status == "approved"]

    def mark_promoted(self, learning_id: int) -> None:
        """Mark an approved learning as promoted (post-mutation)."""
        approval = self._approvals.get(learning_id)
        if approval and approval.status == "approved":
            approval.status = "promoted"

    def get_all(self, org_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """Get all approvals as dicts for the admin API."""
        results = [a for a in self._approvals.values() if not org_id or a.org_id == org_id]
        results.sort(key=lambda a: a.requested_at, reverse=True)
        return [
            {
                "learning_id": a.learning_id,
                "org_id": a.org_id,
                "status": a.status,
                "requested_at": a.requested_at,
                "reviewed_by": a.reviewed_by,
                "review_notes": a.review_notes,
                "learning_preview": a.learning_preview,
                "tool_name": a.tool_name,
                "hit_count": a.hit_count,
            }
            for a in results[:limit]
        ]
