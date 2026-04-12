"""Agent Catalog — A2A Agent Card registry with multi-tenant cascade.

ADR-K8S-027: agents registered as Agent Cards with version, tenant scope,
trust tier, and priority tier. Cascade resolution: user > tenant > builtin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from stronghold.types.agent import AgentIdentity  # noqa: TC001  (dataclass field)

logger = logging.getLogger("stronghold.agents.catalog")

_SCOPE_PRIORITY = {"builtin": 0, "tenant": 1, "user": 2}


@dataclass(frozen=True)
class AgentCard:
    """A2A Agent Card — portable agent description."""

    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    reasoning_strategy: str = "direct"
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    trust_tier: str = "t2"
    priority_tier: str = "P2"
    max_tool_rounds: int = 3
    delegation_mode: str = "none"
    sub_agents: tuple[str, ...] = ()
    model: str = "auto"
    model_fallbacks: tuple[str, ...] = ()
    active: bool = True
    scope: str = "builtin"
    tenant_id: str = ""
    user_id: str = ""

    @classmethod
    def from_identity(
        cls, identity: AgentIdentity, scope: str = "builtin", tenant_id: str = "", user_id: str = ""
    ) -> AgentCard:
        return cls(
            id=identity.name,
            name=identity.name,
            description=identity.description,
            version=identity.version,
            reasoning_strategy=identity.reasoning_strategy,
            tools=identity.tools,
            skills=identity.skills,
            trust_tier=identity.trust_tier,
            priority_tier=getattr(identity, "priority_tier", "P2"),
            max_tool_rounds=identity.max_tool_rounds,
            delegation_mode=identity.delegation_mode,
            sub_agents=identity.sub_agents,
            model=identity.model,
            model_fallbacks=identity.model_fallbacks,
            active=identity.active,
            scope=scope,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": {
                "reasoning_strategy": self.reasoning_strategy,
                "tools": list(self.tools),
                "skills": list(self.skills),
                "max_tool_rounds": self.max_tool_rounds,
                "delegation_mode": self.delegation_mode,
                "sub_agents": list(self.sub_agents),
            },
            "trust_tier": self.trust_tier,
            "priority_tier": self.priority_tier,
            "model": self.model,
            "active": self.active,
        }


def _card_visible(card: AgentCard, tenant_id: str, user_id: str) -> bool:
    """Check if an agent card is visible to the given tenant/user scope."""
    if card.scope == "builtin":
        return True
    if card.scope == "tenant" and tenant_id and card.tenant_id == tenant_id:
        return True
    return bool(card.scope == "user" and user_id and card.user_id == user_id)


class AgentCatalog:
    """Multi-tenant agent catalog with cascade resolution."""

    def __init__(self) -> None:
        self._cards: list[AgentCard] = []

    def register(self, card: AgentCard) -> None:
        self._cards.append(card)

    def resolve(self, agent_id: str, tenant_id: str = "", user_id: str = "") -> AgentCard | None:
        candidates: list[AgentCard] = []
        for card in self._cards:
            if card.id != agent_id:
                continue
            if _card_visible(card, tenant_id, user_id):
                candidates.append(card)
        if not candidates:
            return None
        candidates.sort(key=lambda c: _SCOPE_PRIORITY.get(c.scope, 0), reverse=True)
        return candidates[0]

    def list_agents(self, tenant_id: str = "", user_id: str = "") -> list[AgentCard]:
        seen: dict[str, AgentCard] = {}
        for card in self._cards:
            if not _card_visible(card, tenant_id, user_id):
                continue
            existing = seen.get(card.id)
            if existing is None or _SCOPE_PRIORITY.get(card.scope, 0) > _SCOPE_PRIORITY.get(
                existing.scope, 0
            ):
                seen[card.id] = card
        return sorted(seen.values(), key=lambda c: c.name)

    def list_by_trust_tier(self, tier: str, **kwargs: str) -> list[AgentCard]:
        return [c for c in self.list_agents(**kwargs) if c.trust_tier == tier]

    def list_by_priority_tier(self, tier: str, **kwargs: str) -> list[AgentCard]:
        return [c for c in self.list_agents(**kwargs) if c.priority_tier == tier]
