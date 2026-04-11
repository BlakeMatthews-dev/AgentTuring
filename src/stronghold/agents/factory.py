"""Agent factory: seed from filesystem, load from database.

Boot sequence:
  1. If SQLAlchemy engine provided and agents exist in DB: load from DB.
  2. If not: seed from agents/ directory → persist to DB (if available).
  3. InMemory mode (no DB): always seeds from filesystem.

The agents/ directory is SEED DATA for first boot. After seeding, the database
is the source of truth. CRUD via API, not filesystem edits.

GitAgent format on disk:
  agents/
  ├── PREAMBLE.md          # Shared system preamble (prepended to all souls)
  ├── arbiter/
  │   ├── agent.yaml       # Identity manifest
  │   ├── SOUL.md          # System prompt
  │   └── RULES.md         # Hard constraints (optional)
  └── ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from stronghold.agents.base import Agent
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.types.agent import AgentIdentity

logger = logging.getLogger("stronghold.agents.factory")

_STRATEGY_REGISTRY: dict[str, Any] = {
    "direct": DirectStrategy,
}


def register_strategy(name: str, cls: type) -> None:
    """Register a strategy class for use in agent.yaml."""
    _STRATEGY_REGISTRY[name] = cls


# ── Filesystem parsing ───────────────────────────────────────────────


def _load_preamble(agents_dir: Path) -> str:
    preamble_path = agents_dir / "PREAMBLE.md"
    if preamble_path.exists():
        return preamble_path.read_text(encoding="utf-8")
    logger.warning("No PREAMBLE.md in %s", agents_dir)
    return ""


_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

# Default values for preamble template variables.
# Used when an agent.yaml doesn't declare a variable.
_PREAMBLE_DEFAULTS: dict[str, str] = {
    "agent_name": "Stronghold Agent",
    "agent_description": "a specialist agent operating within the Stronghold platform",
    "capabilities": (
        "You are a **text-based AI assistant**. You can:\n"
        "- Analyze, explain, summarize, compare, and reason about information\n"
        "- Generate and review code\n"
        "- Write professional and creative content\n"
        "- Answer factual questions\n"
        "- Execute **approved tools only** through the Sentinel-validated dispatch system\n"
        "- Remember context within a session and learn from corrections over time"
    ),
    "boundaries": (
        "These are platform limitations, not suggestions:\n"
        "- **No image generation or editing.** Route image requests to the Canvas agent.\n"
        "- **No audio, video, or multimedia.**\n"
        "- **No direct internet access.** Approved tools handle external data.\n"
        "- **No arbitrary code execution** outside Sentinel-approved tools.\n"
        "- **No file system access** outside the approved workspace.\n"
        "- **No cross-tenant data access.** You see only your org's data."
    ),
}


def _render_preamble(template: str, manifest: dict[str, Any]) -> str:
    """Render a preamble template by substituting {{variables}} from the manifest.

    Variables can resolve to full multi-line prompts (e.g., capabilities, boundaries).
    Unresolved variables fall back to _PREAMBLE_DEFAULTS, then to an empty string.
    """
    # Build the variable map: manifest values override defaults
    variables = dict(_PREAMBLE_DEFAULTS)
    variables["agent_name"] = manifest.get("name", variables["agent_name"])
    variables["agent_description"] = manifest.get("description", variables["agent_description"])

    # Any key in the manifest can be a template variable
    for key in ("capabilities", "boundaries"):
        if key in manifest:
            val = manifest[key]
            if isinstance(val, str):
                variables[key] = val.strip()

    def _replace(match: re.Match) -> str:  # type: ignore[type-arg]
        var_name = match.group(1)
        return variables.get(var_name, "")

    return _VAR_PATTERN.sub(_replace, template)


def _parse_agent_dir(agent_dir: Path) -> tuple[dict[str, Any], str, str] | None:
    """Parse a single GitAgent directory → (manifest, soul, rules) or None."""
    manifest_path = agent_dir / "agent.yaml"
    if not manifest_path.exists():
        return None

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "name" not in manifest:
        logger.warning("Invalid agent.yaml in %s — skipping", agent_dir)
        return None

    soul_file = manifest.get("soul", "SOUL.md")
    soul_path = agent_dir / soul_file
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

    rules_path = agent_dir / "RULES.md"
    rules = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

    return manifest, soul, rules


# ── Identity + strategy ──────────────────────────────────────────────


def _safe_tuple(value: Any) -> tuple:
    """Coerce YAML values to tuple safely.

    YAML footguns this protects against (SEC-011, SEC-012):
      - `tools: null` → Python None → tuple(None) raises TypeError
      - `tools: "shell"` → string → tuple iterates chars as ('s','h','e','l','l')
      - `tools: {}` / `tools: 42` → invalid, silently becomes ()
    """
    if value is None:
        return ()
    if isinstance(value, str):
        # Common YAML mistake: `tools: "shell"` meant `tools: [shell]`
        return () if not value else (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _build_identity_from_manifest(manifest: dict[str, Any]) -> AgentIdentity:
    name = manifest["name"]
    reasoning = manifest.get("reasoning", {}) or {}
    return AgentIdentity(
        name=name,
        version=manifest.get("version", "1.0.0"),
        description=manifest.get("description", ""),
        soul_prompt_name=f"agent.{name}.soul",
        model=manifest.get("model", "auto"),
        model_fallbacks=_safe_tuple(manifest.get("model_fallbacks")),
        model_constraints=manifest.get("model_constraints", {}) or {},
        tools=_safe_tuple(manifest.get("tools")),
        skills=_safe_tuple(manifest.get("skills")),
        rules=_safe_tuple(manifest.get("rules")),
        trust_tier=manifest.get("trust_tier", "t2"),
        priority_tier=manifest.get("priority_tier", "P2"),
        max_tool_rounds=reasoning.get("max_subtasks", reasoning.get("max_rounds", 3)),
        reasoning_strategy=reasoning.get("strategy", "direct"),
        memory_config=manifest.get("memory", {}) or {},
        phases=_safe_tuple(reasoning.get("phases")),
    )


def _build_identity_from_record(record: Any) -> AgentIdentity:
    """Build AgentIdentity from an AgentRecord (SQLModel)."""
    return AgentIdentity(
        name=record.name,
        version=record.version,
        description=record.description,
        soul_prompt_name=f"agent.{record.name}.soul",
        model=record.model,
        model_fallbacks=tuple(record.model_fallbacks or []),
        model_constraints=record.model_constraints or {},
        tools=tuple(record.tools or []),
        skills=tuple(record.skills or []),
        rules=tuple(record.rules.splitlines()) if record.rules else (),
        trust_tier=record.trust_tier,
        priority_tier=getattr(record, "priority_tier", "P2"),
        max_tool_rounds=record.max_tool_rounds,
        reasoning_strategy=record.reasoning_strategy,
        memory_config=record.memory_config or {},
    )


def _build_strategy(identity: AgentIdentity) -> Any:
    strategy_name = identity.reasoning_strategy
    strategy_cls = _STRATEGY_REGISTRY.get(strategy_name, DirectStrategy)
    if strategy_cls is DirectStrategy:
        return DirectStrategy()
    try:
        return strategy_cls()
    except TypeError:
        logger.warning(
            "Strategy '%s' requires init args — falling back to direct for '%s'",
            strategy_name,
            identity.name,
        )
        return DirectStrategy()


def _register_custom_strategies() -> None:
    # React strategy (Ranger, Warden-at-Arms, Canvas)
    try:
        from stronghold.agents.strategies.react import ReactStrategy  # noqa: PLC0415

        register_strategy("react", ReactStrategy)
    except ImportError:
        pass

    # Delegate strategy (Arbiter)
    try:
        from stronghold.agents.strategies.delegate import DelegateStrategy  # noqa: PLC0415

        register_strategy("delegate", DelegateStrategy)
    except ImportError:
        pass

    # Builders learning strategy (Frank, Mason, Auditor)
    try:
        from stronghold.agents.strategies.builders_learning import (
            BuildersLearningStrategy,
        )  # noqa: PLC0415

        register_strategy("builders_learning", BuildersLearningStrategy)
    except ImportError:
        pass

    # Artificer custom strategy
    try:
        from stronghold.agents.artificer.strategy import ArtificerStrategy  # noqa: PLC0415

        register_strategy("plan_execute", ArtificerStrategy)
        register_strategy("artificer", ArtificerStrategy)
    except ImportError:
        pass


def _instantiate(identity: AgentIdentity, **deps: Any) -> Agent:
    """Create an Agent runtime object from identity + shared deps."""
    strategy = _build_strategy(identity)
    tool_executor = deps.pop("tool_executor", None)
    return Agent(
        identity=identity,
        strategy=strategy,
        tool_executor=tool_executor if identity.tools else None,
        **deps,
    )


# ── Public API ───────────────────────────────────────────────────────


async def create_agents(
    *,
    agents_dir: str | Path,
    prompt_manager: Any,
    llm: Any,
    context_builder: Any,
    warden: Any,
    sentinel: Any,
    learning_store: Any,
    learning_extractor: Any,
    outcome_store: Any,
    session_store: Any,
    quota_tracker: Any,
    tracer: Any,
    coin_ledger: Any = None,
    tool_executor: Any = None,
    sa_engine: Any = None,
) -> dict[str, Agent]:
    """Load or seed agents, then instantiate runtime Agent objects.

    If sa_engine is provided and agents exist in the DB, loads from DB.
    Otherwise seeds from the agents/ directory and persists to DB if available.
    InMemory mode: always seeds from filesystem.
    """
    _register_custom_strategies()

    deps = {
        "llm": llm,
        "context_builder": context_builder,
        "prompt_manager": prompt_manager,
        "warden": warden,
        "sentinel": sentinel,
        "learning_store": learning_store,
        "learning_extractor": learning_extractor,
        "outcome_store": outcome_store,
        "session_store": session_store,
        "quota_tracker": quota_tracker,
        "coin_ledger": coin_ledger,
        "tracer": tracer,
        "tool_executor": tool_executor,
    }

    # ── Try loading from database first ──
    if sa_engine:
        try:
            from stronghold.persistence.pg_agents import PgAgentRegistry  # noqa: PLC0415

            registry = PgAgentRegistry(sa_engine)
            count = await registry.count()
            if count > 0:
                records = await registry.list_active()
                agents: dict[str, Agent] = {}
                for record in records:
                    identity = _build_identity_from_record(record)
                    # Soul is already in the record — upsert to prompt store for runtime
                    await prompt_manager.upsert(
                        f"agent.{identity.name}.soul",
                        record.soul,
                        label="production",
                    )
                    agents[identity.name] = _instantiate(identity, **{**deps})
                logger.info("Loaded %d agents from database", len(agents))
                return agents
        except Exception:
            logger.warning(
                "Failed to load agents from DB — falling back to filesystem", exc_info=True
            )

    # ── Seed from filesystem ──
    agents_path = Path(agents_dir)
    if not agents_path.is_dir():
        logger.warning("Agents directory %s not found — no agents loaded", agents_dir)
        return {}

    preamble = _load_preamble(agents_path)
    agents = {}

    # Build PgAgentRegistry for persisting (if DB available)
    persist_registry: Any = None
    if sa_engine:
        try:
            from stronghold.persistence.pg_agents import PgAgentRegistry  # noqa: PLC0415

            persist_registry = PgAgentRegistry(sa_engine)
        except Exception:
            pass

    for agent_dir in sorted(agents_path.iterdir()):
        if not agent_dir.is_dir():
            continue

        parsed = _parse_agent_dir(agent_dir)
        if parsed is None:
            continue

        manifest, soul, rules = parsed
        identity = _build_identity_from_manifest(manifest)

        # Render preamble template with agent-specific variables, then prepend to soul
        rendered_preamble = _render_preamble(preamble, manifest)
        full_soul = rendered_preamble + soul

        # Upsert soul to prompt store
        await prompt_manager.upsert(
            f"agent.{identity.name}.soul",
            full_soul,
            label="production",
        )

        # Persist to agents table if DB available
        if persist_registry:
            try:
                from stronghold.models.agent import AgentRecord  # noqa: PLC0415

                record = AgentRecord(
                    name=identity.name,
                    version=identity.version,
                    description=identity.description,
                    soul=full_soul,
                    rules=rules,
                    reasoning_strategy=identity.reasoning_strategy,
                    model=identity.model,
                    model_fallbacks=list(identity.model_fallbacks),
                    model_constraints=identity.model_constraints,
                    tools=list(identity.tools),
                    skills=list(identity.skills),
                    max_tool_rounds=identity.max_tool_rounds,
                    memory_config=identity.memory_config,
                    trust_tier=identity.trust_tier,
                    priority_tier=identity.priority_tier,
                    provenance="builtin",
                    org_id="",
                    preamble=True,
                    active=True,
                )
                await persist_registry.upsert(record)
            except Exception:
                logger.warning("Failed to persist agent '%s' to DB", identity.name, exc_info=True)

        agents[identity.name] = _instantiate(identity, **{**deps})
        logger.info(
            "Seeded agent '%s' (strategy=%s, tools=%d, db=%s)",
            identity.name,
            identity.reasoning_strategy,
            len(identity.tools),
            persist_registry is not None,
        )

    if not agents:
        logger.warning("No agents loaded from %s", agents_dir)

    return agents
