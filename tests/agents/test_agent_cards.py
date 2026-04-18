"""Tests for Agent Card JSON files (ADR-K8S-027)."""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_FIELDS = {"id", "name", "description", "version", "capabilities", "trust_tier", "priority_tier"}
VALID_PRIORITY_TIERS = {"P0", "P1", "P2", "P3", "P4", "P5"}
VALID_TRUST_TIERS = {"t0", "t1", "t2", "t3", "t4"}
VALID_STRATEGIES = {"direct", "react", "plan_execute", "delegate", "custom"}


def _load_cards() -> list[tuple[str, dict]]:
    agents_dir = Path("agents")
    if not agents_dir.exists():
        return []
    cards = []
    for agent_dir in sorted(agents_dir.iterdir()):
        card_path = agent_dir / "agent_card.json"
        if card_path.exists():
            data = json.loads(card_path.read_text())
            cards.append((agent_dir.name, data))
    return cards


def test_all_agents_have_cards() -> None:
    agents_dir = Path("agents")
    if not agents_dir.exists():
        return
    for agent_dir in sorted(agents_dir.iterdir()):
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        card_path = agent_dir / "agent_card.json"
        assert card_path.exists(), f"{agent_dir.name} missing agent_card.json"


def test_card_required_fields() -> None:
    for name, card in _load_cards():
        missing = REQUIRED_FIELDS - set(card.keys())
        assert not missing, f"{name} card missing fields: {missing}"


def test_card_priority_tiers_valid() -> None:
    for name, card in _load_cards():
        tier = card["priority_tier"]
        assert tier in VALID_PRIORITY_TIERS, f"{name}: invalid priority_tier '{tier}'"


def test_card_trust_tiers_valid() -> None:
    for name, card in _load_cards():
        tier = card["trust_tier"]
        assert tier in VALID_TRUST_TIERS, f"{name}: invalid trust_tier '{tier}'"


def test_card_capabilities_structure() -> None:
    for name, card in _load_cards():
        caps = card["capabilities"]
        assert "reasoning_strategy" in caps, f"{name}: missing reasoning_strategy"
        # reasoning_strategy is one of the documented values.
        assert caps["reasoning_strategy"] in VALID_STRATEGIES, (
            f"{name}: invalid reasoning_strategy '{caps['reasoning_strategy']}'"
        )
        assert "tools" in caps, f"{name}: missing tools"
        tools = caps["tools"]
        # tools is a JSON array (not dict, not scalar). Every entry is a string
        # naming a tool.
        assert tools == list(tools), f"{name}: tools must be a list"
        for tool in tools:
            # Exact-type str (not a str subclass that may mangle encoding)
            # and non-empty.
            assert type(tool) is str, (
                f"{name}: each tool must be a str, got {type(tool).__name__}"
            )
            assert tool, f"{name}: tool name must be non-empty, got {tool!r}"


def test_card_id_matches_directory() -> None:
    for name, card in _load_cards():
        assert card["id"] == name, f"Card id '{card['id']}' != directory '{name}'"


def test_card_json_valid() -> None:
    agents_dir = Path("agents")
    if not agents_dir.exists():
        return
    for agent_dir in sorted(agents_dir.iterdir()):
        card_path = agent_dir / "agent_card.json"
        if not card_path.exists():
            continue
        # Should not raise
        json.loads(card_path.read_text())


def test_expected_agents_present() -> None:
    cards = _load_cards()
    names = {name for name, _ in cards}
    expected = {"arbiter", "artificer", "ranger", "scribe", "warden-at-arms"}
    missing = expected - names
    assert not missing, f"Missing agent cards for: {missing}"


def test_priority_tier_assignments() -> None:
    expected = {
        "arbiter": "P1", "artificer": "P2", "auditor": "P3",
        "default": "P1", "ranger": "P1", "scribe": "P1",
        "warden-at-arms": "P1", "frank": "P5", "mason": "P5",
        "davinci": "P2", "fabulist": "P2",
    }
    for name, card in _load_cards():
        if name in expected:
            assert card["priority_tier"] == expected[name], (
                f"{name}: expected {expected[name]}, got {card['priority_tier']}"
            )
