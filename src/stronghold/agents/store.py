"""In-memory agent store with GitAgent import/export.

GitAgent format (zip):
  agent-name/
  ├── agent.yaml     # Manifest (spec_version, name, version, reasoning, model, tools)
  ├── SOUL.md        # System prompt
  ├── RULES.md       # Hard constraints (optional)
  └── skills/        # Agent-specific SKILL.md files (optional)
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from stronghold.agents.base import Agent
    from stronghold.types.agent import AgentIdentity

logger = logging.getLogger("stronghold.agents.store")

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")


class InMemoryAgentStore:
    """In-memory agent store. Wraps the container.agents dict.

    Provides CRUD + GitAgent import/export for the dashboard and API.
    """

    def __init__(
        self,
        agents: dict[str, Agent],
        prompt_manager: Any = None,
    ) -> None:
        self._agents = agents
        self._prompt_manager = prompt_manager
        # Store soul and rules content separately (not on AgentIdentity)
        self._souls: dict[str, str] = {}
        self._rules: dict[str, str] = {}

    async def create(
        self,
        identity: AgentIdentity,
        soul_content: str,
        rules_content: str = "",
    ) -> str:
        """Create and register a new agent."""
        name = identity.name
        if not _NAME_PATTERN.match(name):
            msg = (
                f"Invalid agent name '{name}'. "
                "Must be lowercase alphanumeric + hyphens, 1-50 chars."
            )
            raise ValueError(msg)
        if name in self._agents:
            msg = f"Agent '{name}' already exists"
            raise ValueError(msg)

        # Store soul prompt
        if self._prompt_manager and soul_content:
            await self._prompt_manager.upsert(
                f"agent.{name}.soul", soul_content, label="production"
            )
        self._souls[name] = soul_content
        self._rules[name] = rules_content

        # Create Agent instance with DirectStrategy by default
        from stronghold.agents.base import Agent  # noqa: PLC0415
        from stronghold.agents.strategies.direct import DirectStrategy  # noqa: PLC0415

        strategy_map: dict[str, Any] = {"direct": DirectStrategy}
        try:
            from stronghold.agents.strategies.react import (  # noqa: PLC0415
                ReactStrategy,
            )

            strategy_map["react"] = ReactStrategy
        except ImportError:
            pass

        strategy_cls = strategy_map.get(identity.reasoning_strategy, DirectStrategy)
        strategy = strategy_cls()

        # Get shared dependencies from an existing agent
        ref_agent = next(iter(self._agents.values()), None)
        if ref_agent:
            agent = Agent(
                identity=identity,
                strategy=strategy,
                llm=ref_agent._llm,
                context_builder=ref_agent._context_builder,
                prompt_manager=ref_agent._prompt_manager,
                warden=ref_agent._warden,
                session_store=ref_agent._session_store,
            )
        else:
            msg = "No existing agents to clone dependencies from"
            raise ValueError(msg)

        self._agents[name] = agent
        logger.info("Agent '%s' created (strategy=%s)", name, identity.reasoning_strategy)
        return name

    async def get(self, name: str, org_id: str = "") -> dict[str, Any] | None:
        """Get agent details. If org_id given, only return if agent matches."""
        agent = self._agents.get(name)
        if not agent:
            return None
        identity = agent.identity
        # Org isolation: if caller has org_id, agent must belong to same org or be global
        if org_id and identity.org_id and identity.org_id != org_id:
            return None
        return {
            "name": identity.name,
            "description": identity.description,
            "version": identity.version,
            "reasoning_strategy": identity.reasoning_strategy,
            "model": identity.model,
            "tools": list(identity.tools),
            "trust_tier": identity.trust_tier,
            "max_tool_rounds": identity.max_tool_rounds,
            "soul_prompt_preview": self._souls.get(name, "")[:200],
            "rules_preview": self._rules.get(name, "")[:200],
            "memory_config": identity.memory_config,
            "org_id": identity.org_id,
        }

    async def list_all(self, org_id: str = "") -> list[dict[str, Any]]:
        """List all agents visible to the given org."""
        results = []
        for name in sorted(self._agents):
            detail = await self.get(name, org_id=org_id)
            if detail:
                results.append(detail)
        return results

    async def update(self, name: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update agent config."""
        agent = self._agents.get(name)
        if not agent:
            msg = f"Agent '{name}' not found"
            raise ValueError(msg)

        # Update soul prompt if provided
        if "soul_prompt" in updates and self._prompt_manager:
            await self._prompt_manager.upsert(
                f"agent.{name}.soul", updates["soul_prompt"], label="production"
            )
            self._souls[name] = updates["soul_prompt"]

        if "rules" in updates:
            self._rules[name] = updates["rules"]

        # For identity field updates, we'd need to rebuild the Agent
        # (AgentIdentity is frozen). For now, update soul/rules only.
        result = await self.get(name)
        if not result:
            msg = f"Agent '{name}' not found after update"
            raise ValueError(msg)
        return result

    async def delete(self, name: str) -> bool:
        """Delete an agent."""
        if name not in self._agents:
            return False
        del self._agents[name]
        self._souls.pop(name, None)
        self._rules.pop(name, None)
        logger.info("Agent '%s' deleted", name)
        return True

    async def export_gitagent(self, name: str) -> bytes:
        """Export agent as GitAgent zip file."""
        agent = self._agents.get(name)
        if not agent:
            msg = f"Agent '{name}' not found"
            raise ValueError(msg)

        identity = agent.identity
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # agent.yaml
            manifest = {
                "spec_version": "0.1.0",
                "name": identity.name,
                "version": identity.version,
                "description": identity.description,
                "reasoning": {
                    "strategy": identity.reasoning_strategy,
                    "max_rounds": identity.max_tool_rounds,
                },
                "model": identity.model,
                "tools": list(identity.tools),
                "trust_tier": identity.trust_tier,
                "memory": identity.memory_config,
            }
            zf.writestr(f"{name}/agent.yaml", yaml.dump(manifest, default_flow_style=False))

            # SOUL.md
            soul = self._souls.get(name, "")
            if not soul and self._prompt_manager:
                soul, _ = await self._prompt_manager.get_with_config(
                    f"agent.{name}.soul", label="production"
                )
            zf.writestr(f"{name}/SOUL.md", soul or "")

            # RULES.md
            rules = self._rules.get(name, "")
            if rules:
                zf.writestr(f"{name}/RULES.md", rules)

        return buf.getvalue()

    async def import_gitagent(self, zip_data: bytes) -> str:
        """Import agent from GitAgent zip."""
        buf = io.BytesIO(zip_data)

        with zipfile.ZipFile(buf, "r") as zf:
            # Find agent.yaml
            yaml_files = [n for n in zf.namelist() if n.endswith("/agent.yaml")]
            if not yaml_files:
                msg = "No agent.yaml found in zip"
                raise ValueError(msg)

            yaml_path = yaml_files[0]
            agent_dir = yaml_path.rsplit("/", 1)[0]

            # H4: Zip Slip protection — reject path traversal
            for entry_name in zf.namelist():
                if ".." in entry_name or entry_name.startswith("/"):
                    msg = f"Zip entry contains path traversal: {entry_name!r}"
                    raise ValueError(msg)

            # Parse manifest
            manifest = yaml.safe_load(zf.read(yaml_path))
            if not isinstance(manifest, dict):
                msg = "Invalid agent.yaml format"
                raise ValueError(msg)

            name = manifest.get("name", "")
            if not name:
                msg = "agent.yaml missing 'name' field"
                raise ValueError(msg)

            # Read SOUL.md
            soul_path = f"{agent_dir}/SOUL.md"
            soul = ""
            if soul_path in zf.namelist():
                soul = zf.read(soul_path).decode("utf-8")

            # Read RULES.md
            rules_path = f"{agent_dir}/RULES.md"
            rules = ""
            if rules_path in zf.namelist():
                rules = zf.read(rules_path).decode("utf-8")

        # Build AgentIdentity from manifest
        from stronghold.types.agent import AgentIdentity  # noqa: PLC0415

        reasoning = manifest.get("reasoning", {})
        identity = AgentIdentity(
            name=name,
            version=manifest.get("version", "1.0.0"),
            description=manifest.get("description", ""),
            soul_prompt_name=f"agent.{name}.soul",
            model=manifest.get("model", "auto"),
            tools=tuple(manifest.get("tools", [])),
            trust_tier="t4",  # SECURITY: always untrusted on import, never from manifest
            max_tool_rounds=reasoning.get("max_rounds", 3),
            reasoning_strategy=reasoning.get("strategy", "direct"),
            memory_config=manifest.get("memory", {}),
        )

        # Create the agent
        return await self.create(identity, soul, rules)
