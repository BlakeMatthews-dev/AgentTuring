"""Integration tests for agents/factory.py — filesystem seeding, preamble, validation.

Covers:
- _load_preamble: present vs missing PREAMBLE.md
- _render_preamble: variable substitution, defaults, custom overrides, unknown vars
- _parse_agent_dir: valid dir, missing agent.yaml, malformed YAML, optional files
- _build_identity_from_manifest: all manifest fields map correctly
- _build_strategy: known strategies, unknown falls back to direct, broken init falls back
- register_strategy: custom strategy registration
- create_agents: full filesystem seeding (no DB), empty dir, missing dir
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.factory import (
    _build_identity_from_manifest,
    _build_strategy,
    _load_preamble,
    _parse_agent_dir,
    _render_preamble,
    _PREAMBLE_DEFAULTS,
    create_agents,
    register_strategy,
    _STRATEGY_REGISTRY,
)
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from tests.fakes import (
    FakeLLMClient,
    FakePromptManager,
    FakeQuotaTracker,
    NoopTracingBackend,
)


# ── _load_preamble ─────────────────────────────────────────────────


class TestLoadPreamble:
    def test_returns_content_when_file_exists(self, tmp_path: Path) -> None:
        preamble = tmp_path / "PREAMBLE.md"
        preamble.write_text("# Hello\nThis is the preamble.", encoding="utf-8")
        result = _load_preamble(tmp_path)
        assert result == "# Hello\nThis is the preamble."

    def test_returns_empty_string_when_missing(self, tmp_path: Path) -> None:
        result = _load_preamble(tmp_path)
        assert result == ""

    def test_reads_utf8_content(self, tmp_path: Path) -> None:
        preamble = tmp_path / "PREAMBLE.md"
        preamble.write_text("Preamble with unicode: \u2603", encoding="utf-8")
        result = _load_preamble(tmp_path)
        assert "\u2603" in result


# ── _render_preamble ───────────────────────────────────────────────


class TestRenderPreamble:
    def test_substitutes_agent_name_from_manifest(self) -> None:
        template = "Hello, {{agent_name}}!"
        manifest: dict[str, Any] = {"name": "ranger"}
        result = _render_preamble(template, manifest)
        assert result == "Hello, ranger!"

    def test_substitutes_description_from_manifest(self) -> None:
        template = "You are {{agent_description}}."
        manifest: dict[str, Any] = {"name": "ranger", "description": "a search specialist"}
        result = _render_preamble(template, manifest)
        assert result == "You are a search specialist."

    def test_uses_default_when_manifest_missing_name(self) -> None:
        template = "Hello, {{agent_name}}!"
        manifest: dict[str, Any] = {}
        result = _render_preamble(template, manifest)
        assert result == f"Hello, {_PREAMBLE_DEFAULTS['agent_name']}!"

    def test_uses_default_description_when_missing(self) -> None:
        template = "You are {{agent_description}}."
        manifest: dict[str, Any] = {"name": "test"}
        result = _render_preamble(template, manifest)
        assert _PREAMBLE_DEFAULTS["agent_description"] in result

    def test_custom_capabilities_override_default(self) -> None:
        template = "Capabilities: {{capabilities}}"
        manifest: dict[str, Any] = {
            "name": "test",
            "capabilities": "Can do X and Y",
        }
        result = _render_preamble(template, manifest)
        assert result == "Capabilities: Can do X and Y"

    def test_custom_boundaries_override_default(self) -> None:
        template = "Boundaries: {{boundaries}}"
        manifest: dict[str, Any] = {
            "name": "test",
            "boundaries": "No external access",
        }
        result = _render_preamble(template, manifest)
        assert result == "Boundaries: No external access"

    def test_default_capabilities_used_when_not_in_manifest(self) -> None:
        template = "{{capabilities}}"
        manifest: dict[str, Any] = {"name": "test"}
        result = _render_preamble(template, manifest)
        assert _PREAMBLE_DEFAULTS["capabilities"] in result

    def test_unknown_variable_renders_empty(self) -> None:
        template = "Hello {{nonexistent_var}}!"
        manifest: dict[str, Any] = {"name": "test"}
        result = _render_preamble(template, manifest)
        assert result == "Hello !"

    def test_multiple_variables_in_one_template(self) -> None:
        template = "I am {{agent_name}}, {{agent_description}}."
        manifest: dict[str, Any] = {"name": "arbiter", "description": "the triage agent"}
        result = _render_preamble(template, manifest)
        assert result == "I am arbiter, the triage agent."

    def test_non_string_capabilities_ignored(self) -> None:
        """Non-string values for capabilities/boundaries are not substituted."""
        template = "{{capabilities}}"
        manifest: dict[str, Any] = {"name": "test", "capabilities": 42}
        result = _render_preamble(template, manifest)
        # Should use the default since 42 is not a string
        assert _PREAMBLE_DEFAULTS["capabilities"] in result

    def test_strips_whitespace_from_capabilities(self) -> None:
        template = "[{{capabilities}}]"
        manifest: dict[str, Any] = {"name": "test", "capabilities": "  trimmed  "}
        result = _render_preamble(template, manifest)
        assert result == "[trimmed]"


# ── _parse_agent_dir ───────────────────────────────────────────────


class TestParseAgentDir:
    def test_valid_dir_returns_manifest_soul_rules(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "ranger"
        agent_dir.mkdir()
        manifest = {"name": "ranger", "version": "1.0.0", "description": "search agent"}
        (agent_dir / "agent.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8"
        )
        (agent_dir / "SOUL.md").write_text("You are the ranger.", encoding="utf-8")
        (agent_dir / "RULES.md").write_text("Always cite sources.", encoding="utf-8")

        result = _parse_agent_dir(agent_dir)
        assert result is not None
        parsed_manifest, soul, rules = result
        assert parsed_manifest["name"] == "ranger"
        assert soul == "You are the ranger."
        assert rules == "Always cite sources."

    def test_missing_agent_yaml_returns_none(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "empty_agent"
        agent_dir.mkdir()
        result = _parse_agent_dir(agent_dir)
        assert result is None

    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        """agent.yaml that parses to a non-dict (e.g., a bare string) is rejected."""
        agent_dir = tmp_path / "bad_agent"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("just a string", encoding="utf-8")
        result = _parse_agent_dir(agent_dir)
        assert result is None

    def test_yaml_without_name_returns_none(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "no_name"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text(
            yaml.dump({"version": "1.0.0"}), encoding="utf-8"
        )
        result = _parse_agent_dir(agent_dir)
        assert result is None

    def test_missing_soul_returns_empty_string(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "no_soul"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text(
            yaml.dump({"name": "test"}), encoding="utf-8"
        )
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        _, soul, _ = result
        assert soul == ""

    def test_missing_rules_returns_empty_string(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "no_rules"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text(
            yaml.dump({"name": "test"}), encoding="utf-8"
        )
        (agent_dir / "SOUL.md").write_text("soul text", encoding="utf-8")
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        _, _, rules = result
        assert rules == ""

    def test_custom_soul_filename(self, tmp_path: Path) -> None:
        """agent.yaml can specify a custom soul filename."""
        agent_dir = tmp_path / "custom_soul"
        agent_dir.mkdir()
        manifest = {"name": "custom", "soul": "CUSTOM_SOUL.md"}
        (agent_dir / "agent.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8"
        )
        (agent_dir / "CUSTOM_SOUL.md").write_text("Custom soul.", encoding="utf-8")
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        _, soul, _ = result
        assert soul == "Custom soul."


# ── _build_identity_from_manifest ──────────────────────────────────


class TestBuildIdentityFromManifest:
    def test_minimal_manifest(self) -> None:
        manifest: dict[str, Any] = {"name": "test"}
        identity = _build_identity_from_manifest(manifest)
        assert identity.name == "test"
        assert identity.version == "1.0.0"
        assert identity.description == ""
        assert identity.model == "auto"
        assert identity.reasoning_strategy == "direct"
        assert identity.max_tool_rounds == 3
        assert identity.trust_tier == "t2"
        assert identity.priority_tier == "P2"
        assert identity.tools == ()
        assert identity.skills == ()
        assert identity.rules == ()

    def test_full_manifest(self) -> None:
        manifest: dict[str, Any] = {
            "name": "ranger",
            "version": "2.0.0",
            "description": "search agent",
            "model": "gpt-4",
            "model_fallbacks": ["gpt-3.5"],
            "model_constraints": {"temperature": 0.3},
            "tools": ["web_search", "database_query"],
            "skills": ["summarize"],
            "rules": ["cite sources"],
            "trust_tier": "t1",
            "priority_tier": "P0",
            "reasoning": {
                "strategy": "react",
                "max_rounds": 5,
            },
            "memory": {"learnings": True, "episodic": False},
        }
        identity = _build_identity_from_manifest(manifest)
        assert identity.name == "ranger"
        assert identity.version == "2.0.0"
        assert identity.description == "search agent"
        assert identity.model == "gpt-4"
        assert identity.model_fallbacks == ("gpt-3.5",)
        assert identity.model_constraints == {"temperature": 0.3}
        assert identity.tools == ("web_search", "database_query")
        assert identity.skills == ("summarize",)
        assert identity.rules == ("cite sources",)
        assert identity.trust_tier == "t1"
        assert identity.priority_tier == "P0"
        assert identity.reasoning_strategy == "react"
        assert identity.max_tool_rounds == 5
        assert identity.memory_config == {"learnings": True, "episodic": False}

    def test_max_subtasks_overrides_max_rounds(self) -> None:
        """max_subtasks takes precedence over max_rounds in reasoning config."""
        manifest: dict[str, Any] = {
            "name": "test",
            "reasoning": {"max_subtasks": 10, "max_rounds": 5},
        }
        identity = _build_identity_from_manifest(manifest)
        assert identity.max_tool_rounds == 10

    def test_soul_prompt_name_format(self) -> None:
        manifest: dict[str, Any] = {"name": "arbiter"}
        identity = _build_identity_from_manifest(manifest)
        assert identity.soul_prompt_name == "agent.arbiter.soul"


# ── _build_strategy ────────────────────────────────────────────────


class TestBuildStrategy:
    def test_direct_strategy_for_direct(self) -> None:
        identity = AgentIdentity(name="test", reasoning_strategy="direct")
        strategy = _build_strategy(identity)
        # Exact type identity — a subclass swap would be a regression.
        assert type(strategy) is DirectStrategy

    def test_unknown_strategy_falls_back_to_direct(self) -> None:
        identity = AgentIdentity(name="test", reasoning_strategy="nonexistent")
        strategy = _build_strategy(identity)
        assert type(strategy) is DirectStrategy

    def test_strategy_with_broken_init_falls_back(self) -> None:
        """Strategy class whose __init__ raises TypeError falls back to DirectStrategy."""

        class BrokenStrategy:
            def __init__(self, required_arg: str) -> None:
                pass

        # Register then test
        register_strategy("broken", BrokenStrategy)
        try:
            identity = AgentIdentity(name="test", reasoning_strategy="broken")
            strategy = _build_strategy(identity)
            assert type(strategy) is DirectStrategy
        finally:
            # Clean up the registry
            _STRATEGY_REGISTRY.pop("broken", None)


# ── register_strategy ──────────────────────────────────────────────


class TestRegisterStrategy:
    def test_registers_new_strategy(self) -> None:
        class MyStrategy:
            pass

        register_strategy("my_custom", MyStrategy)
        assert _STRATEGY_REGISTRY["my_custom"] is MyStrategy
        # Clean up
        _STRATEGY_REGISTRY.pop("my_custom", None)

    def test_overwrites_existing(self) -> None:
        class V1:
            pass

        class V2:
            pass

        register_strategy("versioned", V1)
        register_strategy("versioned", V2)
        assert _STRATEGY_REGISTRY["versioned"] is V2
        _STRATEGY_REGISTRY.pop("versioned", None)


# ── create_agents (full integration) ───────────────────────────────


def _make_agents_dir(base: Path, agents: list[dict[str, Any]], preamble: str = "") -> Path:
    """Create a temporary agents/ directory with the given agents."""
    agents_dir = base / "agents"
    agents_dir.mkdir()
    if preamble:
        (agents_dir / "PREAMBLE.md").write_text(preamble, encoding="utf-8")
    for agent in agents:
        name = agent["name"]
        agent_subdir = agents_dir / name
        agent_subdir.mkdir()
        manifest = {k: v for k, v in agent.items() if k != "soul_text" and k != "rules_text"}
        (agent_subdir / "agent.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8"
        )
        soul_text = agent.get("soul_text", f"You are {name}.")
        (agent_subdir / "SOUL.md").write_text(soul_text, encoding="utf-8")
        if "rules_text" in agent:
            (agent_subdir / "RULES.md").write_text(agent["rules_text"], encoding="utf-8")
    return agents_dir


class TestCreateAgentsFilesystem:
    async def test_seeds_agents_from_directory(self, tmp_path: Path) -> None:
        agents_dir = _make_agents_dir(
            tmp_path,
            [
                {"name": "alpha", "version": "1.0.0", "description": "Agent Alpha"},
                {"name": "beta", "version": "1.0.0", "description": "Agent Beta"},
            ],
            preamble="## Preamble\nYou are {{agent_name}}.\n",
        )

        prompts = FakePromptManager()
        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=prompts,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )

        assert "alpha" in result
        assert "beta" in result
        assert len(result) == 2

        # Check that agents are real Agent instances — exact type identity.
        assert type(result["alpha"]) is Agent
        assert type(result["beta"]) is Agent

        # Check identities
        assert result["alpha"].identity.name == "alpha"
        assert result["beta"].identity.description == "Agent Beta"

    async def test_preamble_prepended_to_soul(self, tmp_path: Path) -> None:
        agents_dir = _make_agents_dir(
            tmp_path,
            [{"name": "test", "soul_text": "Agent-specific soul."}],
            preamble="PREAMBLE: {{agent_name}}\n",
        )

        prompts = FakePromptManager()
        await create_agents(
            agents_dir=agents_dir,
            prompt_manager=prompts,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )

        # Prompt should contain both preamble and soul
        soul_content = await prompts.get("agent.test.soul")
        assert soul_content.startswith("PREAMBLE: test\n")
        assert "Agent-specific soul." in soul_content

    async def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        result = await create_agents(
            agents_dir=nonexistent,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert result == {}

    async def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert result == {}

    async def test_skips_non_directories(self, tmp_path: Path) -> None:
        """Files in agents_dir (like PREAMBLE.md) are skipped, not parsed."""
        agents_dir = _make_agents_dir(
            tmp_path,
            [{"name": "valid"}],
            preamble="preamble text",
        )
        # Add a stray file that is NOT a directory
        (agents_dir / "README.md").write_text("stray file", encoding="utf-8")

        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert "valid" in result
        assert len(result) == 1

    async def test_skips_malformed_agent_dirs(self, tmp_path: Path) -> None:
        """Directories without valid agent.yaml are silently skipped."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Valid agent
        valid = agents_dir / "valid"
        valid.mkdir()
        (valid / "agent.yaml").write_text(
            yaml.dump({"name": "valid"}), encoding="utf-8"
        )

        # Invalid agent (no name)
        invalid = agents_dir / "invalid"
        invalid.mkdir()
        (invalid / "agent.yaml").write_text(
            yaml.dump({"version": "1.0.0"}), encoding="utf-8"
        )

        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert "valid" in result
        assert "invalid" not in result

    async def test_agent_with_tools_gets_tool_executor(self, tmp_path: Path) -> None:
        """Agents with tools declared get a tool_executor wired."""
        agents_dir = _make_agents_dir(
            tmp_path,
            [{"name": "ranger", "tools": ["web_search"]}],
        )

        class FakeToolExecutor:
            pass

        executor = FakeToolExecutor()
        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
            tool_executor=executor,
        )
        assert result["ranger"]._tool_executor is executor

    async def test_agent_without_tools_has_no_executor(self, tmp_path: Path) -> None:
        """Agents with no tools declared do NOT get a tool_executor."""
        agents_dir = _make_agents_dir(
            tmp_path,
            [{"name": "scribe", "tools": []}],
        )

        class FakeToolExecutor:
            pass

        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
            tool_executor=FakeToolExecutor(),
        )
        assert result["scribe"]._tool_executor is None

    async def test_seeds_from_real_agents_directory(self) -> None:
        """Smoke test: seed from the actual agents/ directory in the repo."""
        # Locate the repo's agents/ dir relative to this test file (works
        # in dev, CI, and any other environment).
        repo_root = Path(__file__).resolve().parents[2]
        real_agents_dir = repo_root / "agents"
        try:
            if not real_agents_dir.is_dir():
                pytest.skip("Real agents/ directory not available")
        except PermissionError:
            pytest.skip("Cannot access agents/ directory (permission denied)")

        prompts = FakePromptManager()
        result = await create_agents(
            agents_dir=real_agents_dir,
            prompt_manager=prompts,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        # Should load at least arbiter, default, ranger, etc.
        assert len(result) >= 3
        assert "arbiter" in result
        assert "default" in result
        assert "ranger" in result
        for agent in result.values():
            assert type(agent) is Agent

    async def test_no_preamble_still_loads_agents(self, tmp_path: Path) -> None:
        """Agents load even when PREAMBLE.md is missing."""
        agents_dir = _make_agents_dir(
            tmp_path,
            [{"name": "solo", "soul_text": "Solo agent soul."}],
            preamble="",  # No preamble file
        )
        # Remove the PREAMBLE.md that _make_agents_dir would create (it skips empty)
        preamble_file = agents_dir / "PREAMBLE.md"
        if preamble_file.exists():
            preamble_file.unlink()

        prompts = FakePromptManager()
        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=prompts,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert "solo" in result
        soul = await prompts.get("agent.solo.soul")
        assert "Solo agent soul." in soul


# ── _build_identity_from_record ───────────────────────────────────


class TestBuildIdentityFromRecord:
    """Test _build_identity_from_record for the DB-load path."""

    def test_builds_identity_from_record_with_all_fields(self) -> None:
        from stronghold.agents.factory import _build_identity_from_record

        class FakeRecord:
            name = "mason"
            version = "2.1.0"
            description = "builder agent"
            model = "gpt-4"
            model_fallbacks = ["gpt-3.5", "claude-3"]
            model_constraints = {"temperature": 0.2}
            tools = ["github", "shell"]
            skills = ["code_review"]
            rules = "Always run tests\nNever skip linting"
            trust_tier = "t1"
            priority_tier = "P1"
            max_tool_rounds = 8
            reasoning_strategy = "react"
            memory_config = {"learnings": True}

        record = FakeRecord()
        identity = _build_identity_from_record(record)
        assert identity.name == "mason"
        assert identity.version == "2.1.0"
        assert identity.description == "builder agent"
        assert identity.model == "gpt-4"
        assert identity.model_fallbacks == ("gpt-3.5", "claude-3")
        assert identity.model_constraints == {"temperature": 0.2}
        assert identity.tools == ("github", "shell")
        assert identity.skills == ("code_review",)
        assert identity.rules == ("Always run tests", "Never skip linting")
        assert identity.trust_tier == "t1"
        assert identity.priority_tier == "P1"
        assert identity.max_tool_rounds == 8
        assert identity.reasoning_strategy == "react"
        assert identity.memory_config == {"learnings": True}
        assert identity.soul_prompt_name == "agent.mason.soul"

    def test_handles_none_fallbacks_and_constraints(self) -> None:
        from stronghold.agents.factory import _build_identity_from_record

        class FakeRecord:
            name = "minimal"
            version = "1.0.0"
            description = ""
            model = "auto"
            model_fallbacks = None
            model_constraints = None
            tools = None
            skills = None
            rules = None
            trust_tier = "t2"
            max_tool_rounds = 3
            reasoning_strategy = "direct"
            memory_config = None

        record = FakeRecord()
        identity = _build_identity_from_record(record)
        assert identity.model_fallbacks == ()
        assert identity.model_constraints == {}
        assert identity.tools == ()
        assert identity.skills == ()
        assert identity.rules == ()
        assert identity.memory_config == {}

    def test_missing_priority_tier_defaults_to_p2(self) -> None:
        from stronghold.agents.factory import _build_identity_from_record

        class FakeRecord:
            name = "old"
            version = "1.0.0"
            description = ""
            model = "auto"
            model_fallbacks = []
            model_constraints = {}
            tools = []
            skills = []
            rules = ""
            trust_tier = "t2"
            max_tool_rounds = 3
            reasoning_strategy = "direct"
            memory_config = {}
            # Intentionally missing priority_tier attribute

        record = FakeRecord()
        identity = _build_identity_from_record(record)
        assert identity.priority_tier == "P2"


# ── _register_custom_strategies ───────────────────────────────────


class TestRegisterCustomStrategies:
    """Test that _register_custom_strategies loads all available strategies."""

    def test_registers_available_strategies(self) -> None:
        from stronghold.agents.factory import _register_custom_strategies, _STRATEGY_REGISTRY

        _register_custom_strategies()
        # After registration, react and delegate should be available
        assert "react" in _STRATEGY_REGISTRY
        assert "delegate" in _STRATEGY_REGISTRY


# ── _instantiate ──────────────────────────────────────────────────


class TestInstantiate:
    """Test _instantiate wiring logic."""

    def test_agent_with_no_tools_gets_no_executor(self) -> None:
        from stronghold.agents.factory import _instantiate

        identity = AgentIdentity(name="test", tools=(), reasoning_strategy="direct")
        agent = _instantiate(
            identity,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=FakePromptManager(),
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
            tool_executor="should-be-ignored",
        )
        assert agent._tool_executor is None

    def test_agent_with_tools_gets_executor(self) -> None:
        from stronghold.agents.factory import _instantiate

        identity = AgentIdentity(name="test", tools=("github",), reasoning_strategy="direct")
        executor = object()
        agent = _instantiate(
            identity,
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=FakePromptManager(),
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
            tool_executor=executor,
        )
        assert agent._tool_executor is executor


# ── create_agents with phases (manifest with phases) ──────────────


class TestCreateAgentsWithPhases:
    """Test that phases from reasoning config are carried through."""

    async def test_phases_from_manifest_carried_to_identity(self, tmp_path: Path) -> None:
        agents_dir = _make_agents_dir(
            tmp_path,
            [
                {
                    "name": "artificer",
                    "reasoning": {
                        "strategy": "direct",
                        "phases": ["plan", "implement", "review"],
                    },
                }
            ],
        )
        result = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=FakePromptManager(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            warden=Warden(),
            sentinel=None,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            quota_tracker=FakeQuotaTracker(),
            tracer=NoopTracingBackend(),
        )
        assert "artificer" in result
        assert result["artificer"].identity.phases == ("plan", "implement", "review")
