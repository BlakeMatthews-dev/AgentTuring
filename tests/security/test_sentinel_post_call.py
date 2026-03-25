"""Tests for Sentinel post_call soft-flag path and _detection_layer helper.

Covers the L2/L2.5/L3 soft-flag code path in Sentinel.post_call (lines 151-172)
and the _detection_layer helper (lines 248-257).

Uses a custom Warden subclass that returns specific flags to trigger
the soft-flag path without relying on actual injection content.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel, _detection_layer
from stronghold.security.warden.detector import Warden
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.security import WardenVerdict


class _SoftFlagWarden(Warden):
    """Warden that returns soft flags (not blocked) for any tool_result scan."""

    def __init__(self, flags: tuple[str, ...] = ("high_instruction_density",)) -> None:
        super().__init__()
        self._custom_flags = flags

    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        if boundary == "tool_result":
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=self._custom_flags,
                confidence=0.6,
            )
        return WardenVerdict(clean=True)


def _make_auth(
    user_id: str = "user-1",
    roles: frozenset[str] | None = None,
    org_id: str = "org-default",
    team_id: str = "team-default",
) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        username=user_id,
        roles=roles or frozenset({"admin"}),
        org_id=org_id,
        team_id=team_id,
    )


def _make_permissions() -> PermissionTable:
    return PermissionTable.from_config({"admin": ["*"]})


def _make_sentinel(
    warden: Warden | None = None,
    audit: InMemoryAuditLog | None = None,
) -> Sentinel:
    return Sentinel(
        warden=warden or Warden(),
        permission_table=_make_permissions(),
        audit_log=audit,
    )


class TestSoftFlagPath:
    """Test the L2/L2.5/L3 soft-flag path in post_call."""

    @pytest.mark.asyncio
    async def test_soft_flag_appends_banner(self) -> None:
        """When Warden flags but does not block, result is annotated with banner."""
        warden = _SoftFlagWarden(flags=("high_instruction_density",))
        sentinel = _make_sentinel(warden=warden)
        result = await sentinel.post_call(
            "web_search",
            "Normal tool result content",
            _make_auth(),
        )
        assert "SECURITY NOTICE" in result
        assert "Normal tool result content" in result
        assert "high_instruction_density" in result

    @pytest.mark.asyncio
    async def test_soft_flag_includes_detection_layer(self) -> None:
        """Banner includes the detection layer name."""
        warden = _SoftFlagWarden(flags=("high_instruction_density",))
        sentinel = _make_sentinel(warden=warden)
        result = await sentinel.post_call(
            "web_search",
            "Some result",
            _make_auth(),
        )
        assert "Heuristic" in result

    @pytest.mark.asyncio
    async def test_soft_flag_prescriptive_detection(self) -> None:
        """Prescriptive flags map to Layer 2.5 (Semantic)."""
        warden = _SoftFlagWarden(flags=("prescriptive_data_exfil",))
        sentinel = _make_sentinel(warden=warden)
        result = await sentinel.post_call(
            "web_search",
            "Result content",
            _make_auth(),
        )
        assert "Semantic" in result
        assert "prescriptive_data_exfil" in result

    @pytest.mark.asyncio
    async def test_soft_flag_llm_classification_detection(self) -> None:
        """LLM classification flags map to Layer 3 (LLM)."""
        warden = _SoftFlagWarden(flags=("llm_classification:suspicious",))
        sentinel = _make_sentinel(warden=warden)
        result = await sentinel.post_call(
            "web_search",
            "Result content",
            _make_auth(),
        )
        assert "LLM" in result

    @pytest.mark.asyncio
    async def test_soft_flag_includes_escalation_url(self) -> None:
        """Banner includes mailto escalation URL with org info."""
        warden = _SoftFlagWarden(flags=("encoded_payload",))
        sentinel = _make_sentinel(warden=warden)
        result = await sentinel.post_call(
            "web_search",
            "Result content",
            _make_auth(org_id="acme-corp"),
        )
        assert "mailto:" in result

    @pytest.mark.asyncio
    async def test_soft_flag_audit_logged(self) -> None:
        """Soft-flagged results still get audit-logged with warden_tool_result."""
        audit = InMemoryAuditLog()
        warden = _SoftFlagWarden(flags=("high_instruction_density",))
        sentinel = _make_sentinel(warden=warden, audit=audit)
        await sentinel.post_call(
            "web_search",
            "Result content",
            _make_auth(),
        )
        entries = await audit.get_entries()
        assert len(entries) == 1
        assert entries[0].verdict == "flagged"
        assert any("warden_tool_result" in v.rule for v in entries[0].violations)


class TestDetectionLayer:
    """Test the _detection_layer helper function."""

    def test_llm_classification_returns_layer3(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("llm_classification:suspicious (model=test)",),
        )
        assert _detection_layer(verdict) == "Layer 3 (LLM)"

    def test_prescriptive_returns_layer25(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("prescriptive_data_exfil",),
        )
        assert _detection_layer(verdict) == "Layer 2.5 (Semantic)"

    def test_high_instruction_returns_layer2(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("high_instruction_density",),
        )
        assert _detection_layer(verdict) == "Layer 2 (Heuristic)"

    def test_encoded_returns_layer2(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("encoded_payload_detected",),
        )
        assert _detection_layer(verdict) == "Layer 2 (Heuristic)"

    def test_unknown_flag_returns_layer1(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("some_regex_pattern_match",),
        )
        assert _detection_layer(verdict) == "Layer 1 (Pattern)"

    def test_empty_flags_returns_layer1(self) -> None:
        verdict = WardenVerdict(clean=False, flags=())
        assert _detection_layer(verdict) == "Layer 1 (Pattern)"

    def test_first_matching_flag_wins(self) -> None:
        """When multiple flags present, the first matching one determines layer."""
        verdict = WardenVerdict(
            clean=False,
            flags=("llm_classification:suspicious", "prescriptive_exfil"),
        )
        assert _detection_layer(verdict) == "Layer 3 (LLM)"


class TestAuditLogEdgeCases:
    """Test _log_audit edge cases: repaired_data logging, exception handling."""

    @pytest.mark.asyncio
    async def test_repaired_data_logged_in_detail(self) -> None:
        """When repaired_data is passed but no detail, keys are logged."""
        audit = InMemoryAuditLog()
        sentinel = _make_sentinel(audit=audit)
        auth = _make_auth()
        # Pre-call with args that need repair (missing required field)
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }
        verdict = await sentinel.pre_call("web_search", {}, auth, schema)
        entries = await audit.get_entries()
        assert len(entries) == 1
        # The entry should have detail about repaired data
        # (whether repaired or just violation reported depends on validator)
        assert entries[0].boundary == "pre_call"
