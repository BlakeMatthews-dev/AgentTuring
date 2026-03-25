"""Tests for Warden flagged response builder."""

from __future__ import annotations

from stronghold.security.warden.flag_response import (
    build_audit_payload,
    build_flagged_response,
)


class TestBuildFlaggedResponse:
    def test_appends_banner_to_content(self) -> None:
        result = build_flagged_response(
            "original tool output",
            flags=["credential exfiltration"],
            detection_layer="L3_LLM",
        )
        assert result.startswith("original tool output")
        assert "SECURITY NOTICE" in result
        assert "credential exfiltration" in result
        assert "L3_LLM" in result

    def test_includes_flag_id_in_escalation(self) -> None:
        result = build_flagged_response(
            "content",
            flags=["suspicious"],
            detection_layer="L2",
            flag_id="FLAG-001",
        )
        assert "FLAG-001" in result
        assert "mailto:" in result

    def test_custom_escalation_url(self) -> None:
        result = build_flagged_response(
            "content",
            flags=["test"],
            detection_layer="L1",
            escalation_url="https://security.example.com/report",
        )
        assert "https://security.example.com/report" in result

    def test_empty_flags_defaults_to_generic_reason(self) -> None:
        result = build_flagged_response(
            "content", flags=[], detection_layer="L2"
        )
        assert "suspicious content detected" in result

    def test_multiple_flags_joined(self) -> None:
        result = build_flagged_response(
            "content",
            flags=["flag1", "flag2", "flag3"],
            detection_layer="L3",
        )
        assert "flag1; flag2; flag3" in result

    def test_custom_admin_email(self) -> None:
        result = build_flagged_response(
            "content",
            flags=["test"],
            detection_layer="L1",
            admin_email="admin@corp.com",
        )
        assert "admin@corp.com" in result

    def test_original_content_preserved(self) -> None:
        result = build_flagged_response(
            "the original content here",
            flags=["test"],
            detection_layer="L1",
        )
        assert "the original content here" in result

    def test_default_admin_email(self) -> None:
        result = build_flagged_response(
            "content",
            flags=["test"],
            detection_layer="L1",
        )
        assert "security@stronghold.local" in result


class TestBuildAuditPayload:
    def test_basic_payload(self) -> None:
        payload = build_audit_payload(
            tool_name="web_search",
            flags=["suspicious_instruction"],
            detection_layer="L3_LLM",
            user_id="user-123",
            org_id="org-456",
        )
        assert payload["event"] == "tool_result_flagged"
        assert payload["severity"] == "warning"
        assert payload["tool_name"] == "web_search"
        assert payload["flags"] == ["suspicious_instruction"]
        assert payload["user_id"] == "user-123"
        assert payload["org_id"] == "org-456"
        assert payload["requires_review"] is True
        assert payload["action"] == "flagged_and_warned"

    def test_content_preview_truncated(self) -> None:
        payload = build_audit_payload(
            tool_name="test",
            flags=[],
            detection_layer="L1",
            user_id="u",
            org_id="o",
            content_preview="x" * 500,
        )
        assert len(payload["content_preview"]) == 200

    def test_llm_classification_included(self) -> None:
        classification = {"label": "suspicious", "model": "gemini-flash", "tokens": 500}
        payload = build_audit_payload(
            tool_name="test",
            flags=["test"],
            detection_layer="L3",
            user_id="u",
            org_id="o",
            llm_classification=classification,
        )
        assert payload["llm_classification"] == classification

    def test_llm_classification_none_by_default(self) -> None:
        payload = build_audit_payload(
            tool_name="test",
            flags=[],
            detection_layer="L1",
            user_id="u",
            org_id="o",
        )
        assert payload["llm_classification"] is None

    def test_empty_content_preview(self) -> None:
        payload = build_audit_payload(
            tool_name="test",
            flags=[],
            detection_layer="L1",
            user_id="u",
            org_id="o",
            content_preview="",
        )
        assert payload["content_preview"] == ""
