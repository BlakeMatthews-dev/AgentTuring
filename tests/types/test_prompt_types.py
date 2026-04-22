"""Tests for types/prompt.py -- ApprovalRequest dataclass."""

from __future__ import annotations

from datetime import UTC, datetime

from stronghold.types.prompt import ApprovalRequest


class TestApprovalRequestConstruction:
    def test_defaults(self) -> None:
        """ApprovalRequest with required fields gets correct defaults."""
        req = ApprovalRequest(
            prompt_name="agent.default.soul",
            version=1,
            requested_by="admin",
        )
        assert req.prompt_name == "agent.default.soul"
        assert req.version == 1
        assert req.requested_by == "admin"
        assert req.notes == ""
        assert req.status == "pending"
        assert req.reviewed_by == ""
        assert req.review_notes == ""
        # created_at defaults to a real UTC-aware timestamp (not None, not naive).
        assert req.created_at is not None
        assert req.created_at.tzinfo is not None
        # Close to "now" — we just constructed the object.
        now = datetime.now(UTC)
        assert abs((now - req.created_at).total_seconds()) < 60
        assert req.reviewed_at is None

    def test_with_notes(self) -> None:
        """ApprovalRequest preserves custom notes."""
        req = ApprovalRequest(
            prompt_name="agent.artificer.soul",
            version=3,
            requested_by="engineer",
            notes="Improved code generation prompt",
        )
        assert req.notes == "Improved code generation prompt"

