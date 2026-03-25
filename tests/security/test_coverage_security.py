"""Targeted coverage tests for security modules.

Covers missed lines in:
- sentinel/policy.py (lines 151-172 flag response paths, 250-257 detection layer)
- warden/detector.py (lines 152-172 L3 LLM classifier path)
- warden/heuristics.py (lines 69-70 base64 decode failure)
- sentinel/token_optimizer.py (lines 19-21 truncation)
- sentinel/audit.py (line 34 agent filter)
- rate_limiter.py (line 92 eviction interval trigger)
"""

from __future__ import annotations

from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel, _detection_layer
from stronghold.security.sentinel.token_optimizer import (
    MAX_RESULT_LENGTH,
    TRUNCATION_MARKER,
    optimize_result,
)
from stronghold.security.warden.detector import Warden
from stronghold.security.warden.heuristics import detect_encoded_instructions
from stronghold.security.rate_limiter import InMemoryRateLimiter, _EVICTION_INTERVAL
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import RateLimitConfig
from stronghold.types.security import AuditEntry, WardenVerdict

from tests.fakes import FakeLLMClient


# ---------------------------------------------------------------------------
# _detection_layer (policy.py lines 250-257)
# ---------------------------------------------------------------------------


class TestDetectionLayer:
    """Test the _detection_layer helper that infers which Warden layer flagged."""

    def test_layer3_llm_flag(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("llm_classification:suspicious (model=gemini-flash)",),
        )
        assert _detection_layer(verdict) == "Layer 3 (LLM)"

    def test_layer25_semantic_flag(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("prescriptive_exfil_detected",),
        )
        assert _detection_layer(verdict) == "Layer 2.5 (Semantic)"

    def test_layer2_heuristic_high_instruction(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("high_instruction_density (0.35)",),
        )
        assert _detection_layer(verdict) == "Layer 2 (Heuristic)"

    def test_layer2_heuristic_encoded(self) -> None:
        verdict = WardenVerdict(
            clean=False,
            flags=("encoded_instructions (1 found)",),
        )
        assert _detection_layer(verdict) == "Layer 2 (Heuristic)"

    def test_layer1_pattern_fallback(self) -> None:
        """Unknown flag falls through to Layer 1 default."""
        verdict = WardenVerdict(
            clean=False,
            flags=("some_unknown_flag",),
        )
        assert _detection_layer(verdict) == "Layer 1 (Pattern)"

    def test_empty_flags_returns_layer1(self) -> None:
        verdict = WardenVerdict(clean=False, flags=())
        assert _detection_layer(verdict) == "Layer 1 (Pattern)"


# ---------------------------------------------------------------------------
# Sentinel post_call flag response path (policy.py lines 151-172)
# ---------------------------------------------------------------------------


class TestSentinelFlagResponse:
    """Test Sentinel post_call when Warden returns non-blocked flags (soft flag path)."""

    async def test_post_call_soft_flag_builds_flagged_response(self) -> None:
        """When Warden flags but does not block, the result should be annotated
        with the flag banner rather than replaced with a block message."""
        # Build a Warden that returns a soft flag (not blocked) for tool_result
        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("suspicious")
        warden = Warden(llm=fake_llm, classifier_model="test-model")

        # We need a Warden that returns a non-clean, non-blocked verdict.
        # The easiest way is to use heuristic-level content that triggers L2.
        # Instead, let's use a custom approach: create a Sentinel with a
        # purpose-built warden subclass that returns the verdict we want.

        class SoftFlagWarden:
            """Warden stub that returns a soft flag verdict."""

            async def scan(self, content: str, boundary: str) -> WardenVerdict:
                return WardenVerdict(
                    clean=False,
                    blocked=False,
                    flags=("prescriptive_exfil_detected",),
                    confidence=0.7,
                )

        permission_table = PermissionTable(roles={"admin": {"*"}})
        audit_log = InMemoryAuditLog()
        sentinel = Sentinel(
            warden=SoftFlagWarden(),  # type: ignore[arg-type]
            permission_table=permission_table,
            audit_log=audit_log,
        )

        auth = AuthContext(
            user_id="user1",
            org_id="org1",
            team_id="team1",
            roles=frozenset({"admin"}),
        )

        result = await sentinel.post_call("web_search", "some tool output", auth)

        # The result should contain the original content AND the security notice
        assert "some tool output" in result
        assert "SECURITY NOTICE" in result
        assert "prescriptive_exfil_detected" in result

        # Audit log should have an entry with flagged verdict
        entries = await audit_log.get_entries()
        assert len(entries) >= 1
        found_flagged = any(e.verdict == "flagged" for e in entries)
        assert found_flagged

    async def test_post_call_hard_block_replaces_content(self) -> None:
        """When Warden hard-blocks, the result is replaced entirely."""

        class HardBlockWarden:
            async def scan(self, content: str, boundary: str) -> WardenVerdict:
                return WardenVerdict(
                    clean=False,
                    blocked=True,
                    flags=("injection_attempt", "role_override"),
                    confidence=0.9,
                )

        permission_table = PermissionTable(roles={"admin": {"*"}})
        sentinel = Sentinel(
            warden=HardBlockWarden(),  # type: ignore[arg-type]
            permission_table=permission_table,
        )

        auth = AuthContext(
            user_id="user1",
            org_id="org1",
            roles=frozenset({"admin"}),
        )

        result = await sentinel.post_call("tool_x", "evil content here", auth)
        assert "blocked by Warden" in result
        assert "evil content here" not in result


# ---------------------------------------------------------------------------
# Warden L3 LLM classifier path (detector.py lines 152-172)
# ---------------------------------------------------------------------------


class TestWardenL3Classifier:
    """Test the Warden Layer 3 LLM classification path."""

    async def test_l3_suspicious_classification(self) -> None:
        """When L3 classifies as suspicious, verdict should be flagged."""
        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("suspicious")
        warden = Warden(llm=fake_llm, classifier_model="test-classifier")

        # Must pass boundary="tool_result" and content that passes L1-L2.5
        verdict = await warden.scan("Benign looking content", "tool_result")

        assert not verdict.clean
        assert not verdict.blocked
        assert any("llm_classification" in f for f in verdict.flags)
        assert verdict.confidence == 0.8

    async def test_l3_safe_classification(self) -> None:
        """When L3 classifies as safe, verdict should be clean."""
        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("safe")
        warden = Warden(llm=fake_llm, classifier_model="test-classifier")

        verdict = await warden.scan("Normal tool output data", "tool_result")

        assert verdict.clean

    async def test_l3_exception_is_swallowed(self) -> None:
        """When L3 classification throws, Warden returns clean (fail-open)."""

        class FailingLLM:
            async def complete(self, messages: object, model: str, **kw: object) -> dict:
                msg = "LLM service unavailable"
                raise ConnectionError(msg)

        warden = Warden(llm=FailingLLM(), classifier_model="test")  # type: ignore[arg-type]

        verdict = await warden.scan("Normal content", "tool_result")
        assert verdict.clean

    async def test_l3_not_triggered_on_user_input(self) -> None:
        """L3 only runs on tool_result boundary, not user_input."""
        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("suspicious")
        warden = Warden(llm=fake_llm, classifier_model="test-classifier")

        verdict = await warden.scan("Benign content", "user_input")

        # L3 should NOT run for user_input, so no LLM call
        assert verdict.clean
        assert len(fake_llm.calls) == 0

    async def test_l3_not_triggered_without_llm(self) -> None:
        """L3 doesn't run when no LLM client is configured."""
        warden = Warden(llm=None)

        verdict = await warden.scan("Some tool result", "tool_result")
        assert verdict.clean


# ---------------------------------------------------------------------------
# Heuristics: base64 decode failure (heuristics.py lines 69-70)
# ---------------------------------------------------------------------------


class TestHeuristicsBase64Failure:
    """Test base64 decode branch where decoding fails (line 69-70 continue)."""

    def test_invalid_base64_is_skipped(self) -> None:
        """Base64-like strings that fail to decode should be silently skipped."""
        # This string looks like base64 (40+ chars of base64 alphabet)
        # but decodes to garbage that doesn't contain instruction patterns
        invalid_b64 = "A" * 50  # Valid base64 chars but decodes to binary garbage
        findings = detect_encoded_instructions(f"prefix {invalid_b64} suffix")
        # Should not crash, and should return empty (the decoded bytes are
        # all 0x00 which don't match instruction patterns)
        assert findings == []

    def test_non_utf8_base64_is_skipped(self) -> None:
        """Base64 that decodes to non-UTF8 bytes should be silently skipped."""
        import base64

        # Encode raw bytes that are not valid UTF-8
        raw_bytes = bytes(range(128, 200))
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        # Pad to ensure it's 40+ chars
        if len(encoded) < 40:
            encoded = encoded + "A" * (40 - len(encoded))
        findings = detect_encoded_instructions(f"data: {encoded}")
        # Should not crash; errors="ignore" handles non-UTF8
        assert findings == []


# ---------------------------------------------------------------------------
# Token optimizer: truncation path (token_optimizer.py lines 19-21)
# ---------------------------------------------------------------------------


class TestTokenOptimizerTruncation:
    """Test the truncation path when result exceeds MAX_RESULT_LENGTH."""

    def test_short_result_passes_through(self) -> None:
        short = "short result"
        assert optimize_result(short) == short

    def test_long_result_gets_truncated(self) -> None:
        """Result longer than MAX_RESULT_LENGTH should be truncated with marker."""
        long_result = "x" * (MAX_RESULT_LENGTH + 500)
        optimized = optimize_result(long_result)
        assert optimized.endswith(TRUNCATION_MARKER)
        assert len(optimized) <= MAX_RESULT_LENGTH

    def test_long_json_gets_compacted_first(self) -> None:
        """Valid JSON that's over limit should try compaction first."""
        import json

        # Build a JSON string that's over MAX_RESULT_LENGTH with pretty-print
        # but under when compacted
        data = {f"key_{i}": f"value_{i}" for i in range(170)}
        pretty = json.dumps(data, indent=4)
        compact = json.dumps(data, separators=(",", ":"))
        # Verify our test data has the right properties
        assert len(pretty) > MAX_RESULT_LENGTH
        assert len(compact) <= MAX_RESULT_LENGTH
        # optimize_result should compact instead of truncating
        result = optimize_result(pretty)
        assert result == compact

    def test_long_json_still_truncated_if_compact_too_big(self) -> None:
        """JSON that's still too big after compaction gets truncated."""
        import json

        data = {f"key_{i}": "v" * 100 for i in range(500)}
        big_json = json.dumps(data, indent=2)
        result = optimize_result(big_json)
        assert result.endswith(TRUNCATION_MARKER)

    def test_non_json_long_result_truncated(self) -> None:
        """Non-JSON long result goes straight to truncation."""
        long_text = "Hello world. " * 1000
        if len(long_text) > MAX_RESULT_LENGTH:
            result = optimize_result(long_text)
            assert result.endswith(TRUNCATION_MARKER)
            assert len(result) <= MAX_RESULT_LENGTH


# ---------------------------------------------------------------------------
# Audit log: agent_id filter (audit.py line 34)
# ---------------------------------------------------------------------------


class TestAuditAgentFilter:
    """Test the agent_id filter path in InMemoryAuditLog.get_entries()."""

    async def test_filter_by_agent_id(self) -> None:
        log = InMemoryAuditLog()
        await log.log(AuditEntry(user_id="u1", agent_id="agent-a", tool_name="t1"))
        await log.log(AuditEntry(user_id="u1", agent_id="agent-b", tool_name="t2"))
        await log.log(AuditEntry(user_id="u2", agent_id="agent-a", tool_name="t3"))

        # Filter by agent_id only
        results = await log.get_entries(agent_id="agent-a")
        assert len(results) == 2
        assert all(e.agent_id == "agent-a" for e in results)

    async def test_filter_by_agent_id_and_user_id(self) -> None:
        log = InMemoryAuditLog()
        await log.log(AuditEntry(user_id="u1", agent_id="agent-a", tool_name="t1"))
        await log.log(AuditEntry(user_id="u1", agent_id="agent-b", tool_name="t2"))
        await log.log(AuditEntry(user_id="u2", agent_id="agent-a", tool_name="t3"))

        results = await log.get_entries(user_id="u1", agent_id="agent-a")
        assert len(results) == 1
        assert results[0].tool_name == "t1"

    async def test_filter_by_agent_id_no_match(self) -> None:
        log = InMemoryAuditLog()
        await log.log(AuditEntry(user_id="u1", agent_id="agent-a"))

        results = await log.get_entries(agent_id="agent-z")
        assert results == []


# ---------------------------------------------------------------------------
# Rate limiter: eviction interval trigger (rate_limiter.py line 92)
# ---------------------------------------------------------------------------


class TestRateLimiterEviction:
    """Test the periodic eviction path triggered every _EVICTION_INTERVAL checks."""

    async def test_eviction_triggered_after_interval(self) -> None:
        """After _EVICTION_INTERVAL checks, stale keys should be evicted."""
        config = RateLimitConfig(
            requests_per_minute=100000,  # High limit so nothing gets rate-limited
            burst_limit=0,  # Disable burst checking
            enabled=True,
        )
        limiter = InMemoryRateLimiter(config)

        # Manually set check_count to just below the threshold
        limiter._check_count = _EVICTION_INTERVAL - 1

        # Add a stale key with an old timestamp
        import time
        old_ts = time.monotonic() - 600  # 10 minutes ago (> _KEY_EVICTION_AGE_S)
        limiter._windows["stale_key"].append(old_ts)

        # Add a fresh key
        await limiter.record("fresh_key")

        # This check should push count to _EVICTION_INTERVAL and trigger eviction
        allowed, _ = await limiter.check("trigger_key")
        assert allowed

        # The stale key should have been evicted
        assert "stale_key" not in limiter._windows

        # The fresh key should still exist
        assert "fresh_key" in limiter._windows

        # check_count should have been reset to 0
        assert limiter._check_count == 0
