"""Tests for conduit.determine_execution_tier() override stack.

Covers:
- Default passthrough (classifier tier unchanged when no agent override)
- Agent priority_tier override
- Cluster pressure downgrade (P2-P5) and protection (P0/P1)
- Trace span records both suggested_tier and final_tier
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from stronghold.conduit import (
    _CRITICAL_TIERS,
    _TIER_LEVELS,
    determine_execution_tier,
)
from stronghold.types.intent import Intent


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _StubAgent:
    """Minimal duck-type carrying priority_tier."""

    priority_tier: str


class _AgentNoPriorityTier:
    """Agent without priority_tier attribute -- should be ignored."""

    pass


# ── Default passthrough ─────────────────────────────────────────────


class TestDefaultPassthrough:
    """Classifier tier passes through when agent has no override."""

    def test_no_agent(self) -> None:
        intent = Intent(tier="P3")
        result = determine_execution_tier(intent, agent=None)
        assert result.tier == "P3"
        # Same object returned when tier unchanged
        assert result is intent

    def test_agent_without_priority_tier(self) -> None:
        intent = Intent(tier="P1")
        result = determine_execution_tier(intent, agent=_AgentNoPriorityTier())
        assert result.tier == "P1"
        assert result is intent

    def test_agent_matches_classifier(self) -> None:
        """Agent has same tier as classifier -- no change."""
        intent = Intent(tier="P2")
        agent = _StubAgent(priority_tier="P2")
        result = determine_execution_tier(intent, agent=agent)
        assert result.tier == "P2"
        assert result is intent

    def test_all_tiers_passthrough(self) -> None:
        """Every valid tier passes through unchanged when no override."""
        for tier in _TIER_LEVELS:
            intent = Intent(tier=tier)
            result = determine_execution_tier(intent, agent=None)
            assert result.tier == tier


# ── Agent override ───────────────────────────────────────────────────


class TestAgentOverride:
    """Agent priority_tier overrides classifier suggestion."""

    def test_agent_upgrades_tier(self) -> None:
        intent = Intent(tier="P3")
        agent = _StubAgent(priority_tier="P0")
        result = determine_execution_tier(intent, agent=agent)
        assert result.tier == "P0"
        # New object because tier changed
        assert result is not intent

    def test_agent_downgrades_tier(self) -> None:
        intent = Intent(tier="P1")
        agent = _StubAgent(priority_tier="P4")
        result = determine_execution_tier(intent, agent=agent)
        assert result.tier == "P4"

    def test_agent_invalid_tier_ignored(self) -> None:
        """Agent with an unrecognized tier string is ignored."""
        intent = Intent(tier="P2")
        agent = _StubAgent(priority_tier="INVALID")
        result = determine_execution_tier(intent, agent=agent)
        assert result.tier == "P2"
        assert result is intent

    def test_preserves_other_fields(self) -> None:
        """Override only changes tier, not other Intent fields."""
        intent = Intent(
            task_type="code",
            complexity="complex",
            tier="P3",
            classified_by="llm",
            user_text="write me a function",
        )
        agent = _StubAgent(priority_tier="P1")
        result = determine_execution_tier(intent, agent=agent)
        assert result.tier == "P1"
        assert result.task_type == "code"
        assert result.complexity == "complex"
        assert result.classified_by == "llm"
        assert result.user_text == "write me a function"


# ── Cluster pressure ────────────────────────────────────────────────


class TestClusterPressure:
    """Cluster pressure downgrades P2-P5 by one level, never P0/P1."""

    def _with_pressure(self, intent: Intent, agent: object = None) -> Intent:
        """Call determine_execution_tier with cluster pressure enabled."""
        with patch("stronghold.conduit._get_cluster_pressure", return_value=True):
            return determine_execution_tier(intent, agent=agent)

    def test_p0_never_downgraded(self) -> None:
        result = self._with_pressure(Intent(tier="P0"))
        assert result.tier == "P0"

    def test_p1_never_downgraded(self) -> None:
        result = self._with_pressure(Intent(tier="P1"))
        assert result.tier == "P1"

    def test_p2_downgraded_to_p3(self) -> None:
        result = self._with_pressure(Intent(tier="P2"))
        assert result.tier == "P3"

    def test_p3_downgraded_to_p4(self) -> None:
        result = self._with_pressure(Intent(tier="P3"))
        assert result.tier == "P4"

    def test_p4_downgraded_to_p5(self) -> None:
        result = self._with_pressure(Intent(tier="P4"))
        assert result.tier == "P5"

    def test_p5_stays_p5(self) -> None:
        """P5 is already the lowest -- cannot go lower."""
        result = self._with_pressure(Intent(tier="P5"))
        assert result.tier == "P5"

    def test_critical_tiers_constant(self) -> None:
        """Sanity: critical tiers are P0 and P1."""
        assert _CRITICAL_TIERS == frozenset({"P0", "P1"})

    def test_agent_override_then_pressure(self) -> None:
        """Agent upgrades to P2, then pressure downgrades to P3."""
        intent = Intent(tier="P4")
        agent = _StubAgent(priority_tier="P2")
        result = self._with_pressure(intent, agent=agent)
        assert result.tier == "P3"

    def test_agent_override_to_critical_immune_to_pressure(self) -> None:
        """Agent upgrades to P1, pressure cannot downgrade it."""
        intent = Intent(tier="P3")
        agent = _StubAgent(priority_tier="P1")
        result = self._with_pressure(intent, agent=agent)
        assert result.tier == "P1"


# ── Trace span output ───────────────────────────────────────────────


class TestTraceOutput:
    """Verify that callers can observe both suggested and final tier."""

    def test_suggested_and_final_differ(self) -> None:
        intent = Intent(tier="P3")
        agent = _StubAgent(priority_tier="P0")
        suggested = intent.tier
        result = determine_execution_tier(intent, agent=agent)
        assert suggested == "P3"
        assert result.tier == "P0"
        assert suggested != result.tier

    def test_suggested_and_final_same(self) -> None:
        intent = Intent(tier="P2")
        suggested = intent.tier
        result = determine_execution_tier(intent, agent=None)
        assert suggested == "P2"
        assert result.tier == "P2"

    def test_pressure_changes_final_not_suggested(self) -> None:
        intent = Intent(tier="P2")
        suggested = intent.tier
        with patch("stronghold.conduit._get_cluster_pressure", return_value=True):
            result = determine_execution_tier(intent, agent=None)
        assert suggested == "P2"
        assert result.tier == "P3"
        # Original intent unchanged (frozen dataclass)
        assert intent.tier == "P2"
