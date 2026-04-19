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
        assert frozenset({"P0", "P1"}) == _CRITICAL_TIERS

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


# ── Coverage expansion: Conduit class, token estimation, fallback, consent ──


from stronghold.conduit import _CONSENT_AFFIRMATIVE, Conduit  # noqa: E402
from tests.fakes import FakeLLMClient, make_test_container  # noqa: E402


class TestConduitTokenEstimation:
    """Tests for Conduit._estimate_tokens static method."""

    def test_empty_messages(self) -> None:
        result = Conduit._estimate_tokens([])
        assert result == 1  # max(0 // 4, 1)

    def test_string_content(self) -> None:
        msgs = [{"role": "user", "content": "Hello world"}]
        result = Conduit._estimate_tokens(msgs)
        assert result == max(len("Hello world") // 4, 1)

    def test_list_content_with_text_parts(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": "data:..."},
                ],
            }
        ]
        result = Conduit._estimate_tokens(msgs)
        assert result >= 1

    def test_multiple_messages(self) -> None:
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello world, this is a test."},
        ]
        result = Conduit._estimate_tokens(msgs)
        total_chars = len("You are helpful.") + len("Hello world, this is a test.")
        assert result == max(total_chars // 4, 1)

    def test_missing_content_key(self) -> None:
        msgs = [{"role": "user"}]
        result = Conduit._estimate_tokens(msgs)
        assert result == 1


class TestConduitFallbackAgent:
    """Tests for Conduit._fallback_agent_name and _fallback_agent."""

    def test_preferred_agent_found(self) -> None:
        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.direct import DirectStrategy
        from stronghold.memory.learnings.store import InMemoryLearningStore
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity

        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        prompts = InMemoryPromptManager()
        agent = Agent(
            identity=AgentIdentity(
                name="coder",
                soul_prompt_name="agent.coder.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
        )
        container = make_test_container(fake_llm=llm, agents={"coder": agent})
        conduit = Conduit(container)
        assert conduit._fallback_agent_name("coder") == "coder"

    def test_fallback_to_arbiter(self) -> None:
        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.direct import DirectStrategy
        from stronghold.memory.learnings.store import InMemoryLearningStore
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity

        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        prompts = InMemoryPromptManager()
        arbiter = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
        )
        container = make_test_container(fake_llm=llm, agents={"arbiter": arbiter})
        conduit = Conduit(container)
        # Preferred agent "missing" falls back to arbiter
        assert conduit._fallback_agent_name("missing_agent") == "arbiter"

    def test_fallback_to_first_available(self) -> None:
        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.direct import DirectStrategy
        from stronghold.memory.learnings.store import InMemoryLearningStore
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity

        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        prompts = InMemoryPromptManager()
        custom = Agent(
            identity=AgentIdentity(
                name="custom",
                soul_prompt_name="agent.custom.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
        )
        container = make_test_container(fake_llm=llm, agents={"custom": custom})
        conduit = Conduit(container)
        # No arbiter, no default, falls back to first available
        assert conduit._fallback_agent_name("missing") == "custom"

    def test_no_agents_raises(self) -> None:
        import pytest

        container = make_test_container(agents={})
        conduit = Conduit(container)
        with pytest.raises(RuntimeError, match="No agents"):
            conduit._fallback_agent_name("anything")


class TestConsentAffirmative:
    """Test the consent affirmative word set."""

    def test_yes_variants(self) -> None:
        for word in ("yes", "yeah", "sure", "ok", "okay", "yep", "y"):
            assert word in _CONSENT_AFFIRMATIVE

    def test_no_is_not_consent(self) -> None:
        assert "no" not in _CONSENT_AFFIRMATIVE
        assert "never" not in _CONSENT_AFFIRMATIVE


class TestBuildResponse:
    """Tests for Conduit._build_response static method."""

    def test_basic_response_structure(self) -> None:
        result = Conduit._build_response(
            response_id="test-id",
            model="gpt-4",
            content="Hello",
            routing={"agent": "arbiter"},
        )
        assert result["id"] == "test-id"
        assert result["model"] == "gpt-4"
        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["content"] == "Hello"
        assert result["_routing"]["agent"] == "arbiter"
        assert result["usage"] == {}  # no include_usage

    def test_response_with_usage(self) -> None:
        result = Conduit._build_response(
            response_id="test-id",
            model="gpt-4",
            content="Hello",
            routing={},
            include_usage=True,
        )
        assert result["usage"]["prompt_tokens"] == 0
        assert result["usage"]["total_tokens"] == 0

    def test_response_finish_reason(self) -> None:
        result = Conduit._build_response(
            response_id="x",
            model="m",
            content="c",
            routing={},
        )
        assert result["choices"][0]["finish_reason"] == "stop"


class TestConduitSessionEviction:
    """Test the session map eviction logic via MAX_STICKY_SESSIONS."""

    def test_max_sticky_sessions_constant(self) -> None:
        assert Conduit._MAX_STICKY_SESSIONS == 10_000
