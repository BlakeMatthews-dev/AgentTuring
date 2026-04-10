"""Tests for AgentCatalog (ADR-K8S-027)."""

from __future__ import annotations

from stronghold.agents.catalog import AgentCard, AgentCatalog
from stronghold.types.agent import AgentIdentity


def _card(name: str, scope: str = "builtin", tenant_id: str = "", user_id: str = "",
          trust_tier: str = "t1", priority_tier: str = "P2") -> AgentCard:
    return AgentCard(
        id=name, name=name, description=f"{name} agent",
        scope=scope, tenant_id=tenant_id, user_id=user_id,
        trust_tier=trust_tier, priority_tier=priority_tier,
    )


def test_register_and_resolve() -> None:
    cat = AgentCatalog()
    cat.register(_card("ranger"))
    result = cat.resolve("ranger")
    assert result is not None
    assert result.name == "ranger"


def test_resolve_unknown() -> None:
    assert AgentCatalog().resolve("nonexistent") is None


def test_tenant_override() -> None:
    cat = AgentCatalog()
    cat.register(_card("ranger", scope="builtin"))
    cat.register(_card("ranger", scope="tenant", tenant_id="acme"))
    result = cat.resolve("ranger", tenant_id="acme")
    assert result is not None
    assert result.scope == "tenant"


def test_user_override() -> None:
    cat = AgentCatalog()
    cat.register(_card("ranger", scope="builtin"))
    cat.register(_card("ranger", scope="tenant", tenant_id="acme"))
    cat.register(_card("ranger", scope="user", user_id="alice"))
    result = cat.resolve("ranger", user_id="alice")
    assert result is not None
    assert result.scope == "user"


def test_list_agents_cascaded() -> None:
    cat = AgentCatalog()
    cat.register(_card("ranger"))
    cat.register(_card("scribe"))
    cat.register(_card("scribe", scope="tenant", tenant_id="acme"))
    agents = cat.list_agents(tenant_id="acme")
    names = [a.name for a in agents]
    assert sorted(names) == ["ranger", "scribe"]
    scribe = next(a for a in agents if a.name == "scribe")
    assert scribe.scope == "tenant"


def test_tenant_isolation() -> None:
    cat = AgentCatalog()
    cat.register(_card("secret-agent", scope="tenant", tenant_id="acme"))
    assert cat.resolve("secret-agent", tenant_id="evil") is None


def test_list_by_trust_tier() -> None:
    cat = AgentCatalog()
    cat.register(_card("arbiter", trust_tier="t0"))
    cat.register(_card("ranger", trust_tier="t1"))
    cat.register(_card("custom", trust_tier="t2"))
    assert len(cat.list_by_trust_tier("t0")) == 1
    assert len(cat.list_by_trust_tier("t1")) == 1


def test_list_by_priority_tier() -> None:
    cat = AgentCatalog()
    cat.register(_card("arbiter", priority_tier="P1"))
    cat.register(_card("mason", priority_tier="P5"))
    cat.register(_card("ranger", priority_tier="P1"))
    assert len(cat.list_by_priority_tier("P1")) == 2
    assert len(cat.list_by_priority_tier("P5")) == 1


def test_from_identity() -> None:
    identity = AgentIdentity(
        name="artificer", version="2.0.0", description="Code agent",
        tools=("shell", "git"), trust_tier="t1",
    )
    card = AgentCard.from_identity(identity)
    assert card.id == "artificer"
    assert card.version == "2.0.0"
    assert card.tools == ("shell", "git")
    assert card.trust_tier == "t1"
    assert card.scope == "builtin"


def test_to_dict() -> None:
    card = _card("ranger", trust_tier="t1", priority_tier="P1")
    d = card.to_dict()
    assert d["id"] == "ranger"
    assert d["trust_tier"] == "t1"
    assert d["priority_tier"] == "P1"
    assert "tools" in d["capabilities"]


def test_empty_catalog_returns_nothing() -> None:
    cat = AgentCatalog()
    assert cat.list_agents() == []
    assert cat.resolve("x") is None
    assert cat.list_by_trust_tier("t1") == []


def test_duplicate_deduplicates_in_list() -> None:
    cat = AgentCatalog()
    cat.register(_card("ranger", priority_tier="P1"))
    cat.register(_card("ranger", priority_tier="P2"))
    assert len(cat.list_agents()) == 1
