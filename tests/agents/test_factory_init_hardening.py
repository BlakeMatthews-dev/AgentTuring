"""Tests for agent initialization hardening.

Covers the fixes laid out in the agent-init hardening spec:
  - AC-1: Manifest validation rejects malformed YAML (dict tools, string tools)
  - AC-2: Quartermaster manifest parses cleanly
  - AC-3: DelegateStrategy is constructed with routing derived from sub_agents
  - AC-4: plan_execute resolves to PlanExecuteStrategy, artificer to ArtificerStrategy
  - AC-5: learning_promoter is injected at agent construction
  - AC-7: Unknown tool names fail at boot, not runtime
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.factory import (
    _build_identity_from_manifest,
    _build_strategy,
    create_agents,
)
from stronghold.agents.strategies.delegate import DelegateStrategy
from stronghold.agents.strategies.plan_execute import PlanExecuteStrategy
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.errors import ConfigError
from tests.fakes import (
    FakeLLMClient,
    FakePromptManager,
    FakeQuotaTracker,
    NoopTracingBackend,
)

# ── AC-1: Manifest validation ──────────────────────────────────────


class TestManifestValidation:
    def test_dict_tools_raises_manifest_error(self) -> None:
        """tools as list of dicts (quartermaster's bug) raises ConfigError, not silent coercion."""
        manifest: dict[str, Any] = {
            "name": "bad",
            "tools": [{"name": "VaultClient"}, {"name": "QuotaTracker"}],
        }
        with pytest.raises(ConfigError, match="tools"):
            _build_identity_from_manifest(manifest)

    def test_string_tools_raises_manifest_error(self) -> None:
        """tools: 'shell' (typo for [shell]) raises rather than silently becoming ('shell',)."""
        manifest: dict[str, Any] = {"name": "bad", "tools": "shell"}
        with pytest.raises(ConfigError, match="tools"):
            _build_identity_from_manifest(manifest)

    def test_dict_skills_raises_manifest_error(self) -> None:
        manifest: dict[str, Any] = {
            "name": "bad",
            "skills": [{"name": "budget_analysis"}],
        }
        with pytest.raises(ConfigError, match="skills"):
            _build_identity_from_manifest(manifest)

    def test_null_tools_becomes_empty_tuple(self) -> None:
        """tools: null is allowed (YAML quirk); coerces to empty tuple."""
        manifest: dict[str, Any] = {"name": "ok", "tools": None}
        identity = _build_identity_from_manifest(manifest)
        assert identity.tools == ()

    def test_missing_tools_becomes_empty_tuple(self) -> None:
        manifest: dict[str, Any] = {"name": "ok"}
        identity = _build_identity_from_manifest(manifest)
        assert identity.tools == ()

    def test_valid_list_of_strings_accepted(self) -> None:
        manifest: dict[str, Any] = {"name": "ok", "tools": ["file_ops", "shell"]}
        identity = _build_identity_from_manifest(manifest)
        assert identity.tools == ("file_ops", "shell")


# ── AC-2: Quartermaster loads cleanly ──────────────────────────────


class TestQuartermasterManifest:
    def test_real_quartermaster_yaml_parses(self) -> None:
        """The on-disk quartermaster manifest must round-trip through the parser."""
        path = Path(__file__).resolve().parents[2] / "agents" / "quartermaster" / "agent.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        identity = _build_identity_from_manifest(raw)
        # Identity must reflect the spec-emitter role described in SOUL.md
        assert identity.name == "quartermaster"
        assert all(isinstance(t, str) for t in identity.tools)
        assert identity.priority_tier in {"P0", "P1", "P2", "P3", "P4", "P5"}
        assert identity.trust_tier.startswith("t")


# ── AC-3: DelegateStrategy is built with routing ───────────────────


class TestDelegateStrategy:
    def test_delegate_strategy_built_when_sub_agents_present(self) -> None:
        """Arbiter-shaped identity yields a real DelegateStrategy, not DirectStrategy."""
        identity = AgentIdentity(
            name="arbiter",
            reasoning_strategy="delegate",
            sub_agents=("artificer", "ranger", "scribe"),
        )
        strategy = _build_strategy(identity)
        assert type(strategy) is DelegateStrategy

    def test_delegate_routing_table_restricted_to_declared_sub_agents(self) -> None:
        identity = AgentIdentity(
            name="arbiter",
            reasoning_strategy="delegate",
            sub_agents=("artificer", "ranger"),
        )
        strategy = _build_strategy(identity)
        assert isinstance(strategy, DelegateStrategy)
        # Internal routing must only contain agents the arbiter declared
        for target in strategy._routing.values():
            assert target in {"artificer", "ranger"}

    def test_delegate_with_no_sub_agents_raises(self) -> None:
        """delegate without sub_agents is a config error — the agent has nothing to delegate to."""
        identity = AgentIdentity(name="arbiter", reasoning_strategy="delegate", sub_agents=())
        with pytest.raises(ConfigError, match="sub_agents"):
            _build_strategy(identity)


# ── AC-4: plan_execute / artificer mapping ─────────────────────────


class TestStrategyMapping:
    def test_plan_execute_returns_plan_execute_strategy(self) -> None:
        """Scribe's plan_execute must NOT silently become ArtificerStrategy."""
        from stronghold.agents.factory import _register_custom_strategies

        _register_custom_strategies()
        identity = AgentIdentity(name="scribe", reasoning_strategy="plan_execute")
        strategy = _build_strategy(identity)
        assert type(strategy) is PlanExecuteStrategy

    def test_artificer_strategy_name_returns_artificer(self) -> None:
        from stronghold.agents.artificer.strategy import ArtificerStrategy
        from stronghold.agents.factory import _register_custom_strategies

        _register_custom_strategies()
        identity = AgentIdentity(name="artificer", reasoning_strategy="artificer")
        strategy = _build_strategy(identity)
        assert type(strategy) is ArtificerStrategy


# ── AC-5: learning_promoter is injected ────────────────────────────


@pytest.mark.asyncio
async def test_learning_promoter_passed_to_agents(tmp_path: Path) -> None:
    """create_agents must accept and propagate learning_promoter to every Agent."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "PREAMBLE.md").write_text("preamble", encoding="utf-8")
    sub = agents_dir / "tester"
    sub.mkdir()
    (sub / "agent.yaml").write_text(
        yaml.dump({"name": "tester", "version": "1.0.0"}), encoding="utf-8"
    )
    (sub / "SOUL.md").write_text("you are tester", encoding="utf-8")

    learning_store = InMemoryLearningStore()
    promoter = LearningPromoter(learning_store, threshold=3)

    agents = await create_agents(
        agents_dir=agents_dir,
        prompt_manager=FakePromptManager(),
        llm=FakeLLMClient(),
        context_builder=ContextBuilder(),
        warden=Warden(),
        sentinel=None,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
        quota_tracker=FakeQuotaTracker(),
        tracer=NoopTracingBackend(),
        learning_promoter=promoter,
    )
    assert "tester" in agents
    agent = agents["tester"]
    assert isinstance(agent, Agent)
    # The promoter must propagate, not be silently dropped to None
    assert agent._learning_promoter is promoter


# ── AC-7/AC-8: Tool schema resolution from the registry ────────────


class TestToolSchemaResolution:
    def test_registered_tool_schema_uses_registry_definition(self) -> None:
        """A registered tool must surface its real parameters, not a `Run X` stub."""
        from stronghold.agents.base import _build_tool_schema
        from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF
        from stronghold.tools.registry import InMemoryToolRegistry

        registry = InMemoryToolRegistry()
        registry.register(FILE_OPS_TOOL_DEF)

        schema = _build_tool_schema("file_ops", registry=registry)

        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "file_ops"
        # Real parameters from ToolDefinition, not the stub `{}` shape
        assert fn["parameters"] == FILE_OPS_TOOL_DEF.parameters
        assert fn["description"] == FILE_OPS_TOOL_DEF.description

    def test_unregistered_tool_falls_back_to_stub(self) -> None:
        """Tools not in the registry still get a callable schema (does not crash)."""
        from stronghold.agents.base import _build_tool_schema
        from stronghold.tools.registry import InMemoryToolRegistry

        registry = InMemoryToolRegistry()
        schema = _build_tool_schema("does_not_exist", registry=registry)
        assert schema["function"]["name"] == "does_not_exist"
        # Stub shape — empty params, generic description
        assert schema["function"]["parameters"]["type"] == "object"


# ── Integration: every real on-disk agent loads ───────────────────


@pytest.mark.asyncio
async def test_real_agents_dir_loads_without_config_error() -> None:
    """Smoke test: every shipped agent.yaml parses end-to-end through create_agents.

    Prior bugs (quartermaster's dict-tools, scribe's plan_execute → ArtificerStrategy)
    only surfaced at request time. This test forces them to surface at boot.
    """
    agents_dir = Path(__file__).resolve().parents[2] / "agents"
    assert agents_dir.is_dir(), f"agents dir not found at {agents_dir}"

    learning_store = InMemoryLearningStore()
    agents = await create_agents(
        agents_dir=agents_dir,
        prompt_manager=FakePromptManager(),
        llm=FakeLLMClient(),
        context_builder=ContextBuilder(),
        warden=Warden(),
        sentinel=None,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
        quota_tracker=FakeQuotaTracker(),
        tracer=NoopTracingBackend(),
        learning_promoter=LearningPromoter(learning_store, threshold=3),
    )

    # All shipped agents must load
    expected = {
        "arbiter",
        "archie",
        "artificer",
        "auditor",
        "davinci",
        "default",
        "fabulist",
        "frank",
        "herald",
        "mason",
        "master-at-arms",
        "quartermaster",
        "ranger",
        "scribe",
        "warden-at-arms",
    }
    assert expected.issubset(agents.keys())

    # Arbiter actually got DelegateStrategy (not the silent DirectStrategy fallback).
    arbiter = agents["arbiter"]
    assert type(arbiter._strategy).__name__ == "DelegateStrategy"
    # Routing must be restricted to declared sub_agents — not leak `mason`/`auditor`/etc.
    declared = set(arbiter.identity.sub_agents)
    assert all(target in declared for target in arbiter._strategy._routing.values())

    # Scribe: plan_execute → PlanExecuteStrategy, NOT ArtificerStrategy.
    scribe = agents["scribe"]
    assert type(scribe._strategy).__name__ == "PlanExecuteStrategy"

    # Artificer: keeps its bespoke strategy.
    artificer = agents["artificer"]
    assert type(artificer._strategy).__name__ == "ArtificerStrategy"

    # learning_promoter must reach every agent — silent None breaks auto-promotion.
    for agent in agents.values():
        assert agent._learning_promoter is not None, (
            f"agent {agent.identity.name} did not receive learning_promoter"
        )
