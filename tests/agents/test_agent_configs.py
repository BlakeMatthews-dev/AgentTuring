"""Tests for Quartermaster and Archie agent configurations.

Spec: specs/phase4-agent-configs.yaml
Validates that agent.yaml files parse correctly and have expected fields.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


class TestQuartermasterConfig:
    def test_parses_without_error(self) -> None:
        """Invariant: valid_manifest."""
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["name"] == "quartermaster"

    def test_priority_tier(self) -> None:
        """Quartermaster is the spec-emitter (Builder pipeline), priority P4 per agent_card.json."""
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["priority_tier"] == "P4"

    def test_has_soul(self) -> None:
        soul_path = _AGENTS_DIR / "quartermaster" / "SOUL.md"
        assert soul_path.exists()
        content = soul_path.read_text()
        assert "Quartermaster" in content

    def test_strategy_is_react(self) -> None:
        """Reasoning strategy lives under `reasoning.strategy` (the parser's contract)."""
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["reasoning"]["strategy"] == "react"

    def test_tools_match_agent_card(self) -> None:
        """Quartermaster only needs github + file_ops to read issues and emit Specs."""
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["tools"] == ["github", "file_ops"]


class TestArchieConfig:
    def test_parses_without_error(self) -> None:
        """Invariant: valid_manifest."""
        manifest_path = _AGENTS_DIR / "archie" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["name"] == "archie"

    def test_priority_tier(self) -> None:
        """Invariant: correct_priority."""
        manifest_path = _AGENTS_DIR / "archie" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["priority_tier"] == "P5"

    def test_has_soul(self) -> None:
        soul_path = _AGENTS_DIR / "archie" / "SOUL.md"
        assert soul_path.exists()
        content = soul_path.read_text()
        assert "Archie" in content
        assert "generate_property_tests" in content

    def test_strategy_is_direct(self) -> None:
        manifest_path = _AGENTS_DIR / "archie" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["reasoning"]["strategy"] == "direct"

    def test_no_implementation_rule(self) -> None:
        manifest_path = _AGENTS_DIR / "archie" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        rules = manifest.get("rules", [])
        assert any("MUST-NEVER write implementation" in r for r in rules)
