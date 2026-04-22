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
        """Invariant: correct_priority."""
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["priority_tier"] == "P4"

    def test_has_soul(self) -> None:
        soul_path = _AGENTS_DIR / "quartermaster" / "SOUL.md"
        assert soul_path.exists()
        content = soul_path.read_text()
        assert "Quartermaster" in content
        assert "emit_spec" in content

    def test_strategy_is_direct(self) -> None:
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["reasoning"]["strategy"] == "direct"

    def test_trust_tier_t1(self) -> None:
        manifest_path = _AGENTS_DIR / "quartermaster" / "agent.yaml"
        with manifest_path.open() as f:
            manifest = yaml.safe_load(f)
        assert manifest["trust_tier"] == "t1"


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
