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
        assert isinstance(req.created_at, datetime)
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

    def test_created_at_is_utc(self) -> None:
        """created_at defaults to UTC timezone."""
        req = ApprovalRequest(
            prompt_name="test",
            version=1,
            requested_by="admin",
        )
        assert req.created_at.tzinfo is not None


class TestApprovalRequestStatusTransitions:
    def test_approve_transition(self) -> None:
        """Status can be changed from pending to approved."""
        req = ApprovalRequest(
            prompt_name="agent.default.soul",
            version=2,
            requested_by="engineer",
        )
        assert req.status == "pending"
        req.status = "approved"
        req.reviewed_by = "admin"
        req.review_notes = "Looks good"
        req.reviewed_at = datetime.now(UTC)

        assert req.status == "approved"
        assert req.reviewed_by == "admin"
        assert req.review_notes == "Looks good"
        assert req.reviewed_at is not None

    def test_reject_transition(self) -> None:
        """Status can be changed from pending to rejected."""
        req = ApprovalRequest(
            prompt_name="agent.default.soul",
            version=2,
            requested_by="engineer",
        )
        req.status = "rejected"
        req.reviewed_by = "security-lead"
        req.review_notes = "Contains unsafe patterns"

        assert req.status == "rejected"
        assert req.reviewed_by == "security-lead"


class TestApprovalRequestFields:
    def test_all_fields_accessible(self) -> None:
        """All fields on ApprovalRequest are accessible."""
        now = datetime.now(UTC)
        req = ApprovalRequest(
            prompt_name="test.prompt",
            version=5,
            requested_by="user-1",
            notes="test notes",
            status="approved",
            reviewed_by="admin-1",
            review_notes="approved notes",
            created_at=now,
            reviewed_at=now,
        )
        assert req.prompt_name == "test.prompt"
        assert req.version == 5
        assert req.requested_by == "user-1"
        assert req.notes == "test notes"
        assert req.status == "approved"
        assert req.reviewed_by == "admin-1"
        assert req.review_notes == "approved notes"
        assert req.created_at == now
        assert req.reviewed_at == now
