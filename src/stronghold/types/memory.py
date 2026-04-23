"""Memory types: learnings, episodic memory, tiers, scopes.

The 7-tier episodic memory system with bounded weights.
Key insight: REGRET weight cannot drop below 0.6 — structurally unforgettable.
SessionCheckpoint: typed snapshot of working state for cross-session handoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class MemoryTier(StrEnum):
    """Episodic memory confidence tiers with increasing weight bounds."""

    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    LESSON = "lesson"
    REGRET = "regret"
    AFFIRMATION = "affirmation"
    WISDOM = "wisdom"


# Weight bounds per tier — the key design:
# Regrets (weight >= 0.6) are structurally unforgettable.
# Wisdom (weight >= 0.9) survives across versions.
WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION: (0.1, 0.5),
    MemoryTier.HYPOTHESIS: (0.2, 0.6),
    MemoryTier.OPINION: (0.3, 0.8),
    MemoryTier.LESSON: (0.5, 0.9),
    MemoryTier.REGRET: (0.6, 1.0),
    MemoryTier.AFFIRMATION: (0.6, 1.0),
    MemoryTier.WISDOM: (0.9, 1.0),
}

# Inheritance priority — higher = survives pruning longer
INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION: 1,
    MemoryTier.HYPOTHESIS: 2,
    MemoryTier.OPINION: 3,
    MemoryTier.LESSON: 4,
    MemoryTier.REGRET: 5,
    MemoryTier.AFFIRMATION: 5,
    MemoryTier.WISDOM: 6,
}

REINFORCE_DELTA: float = 0.05
CONTRADICT_DELTA: float = 0.05


class MemoryScope(StrEnum):
    """Memory visibility scopes — hierarchical from broadest to narrowest.

    GLOBAL: visible to all orgs, all teams, all users
    ORGANIZATION: visible to all teams within an org
    TEAM: visible to all users within a team
    USER: visible to this user across all their teams
    AGENT: visible only to this agent instance
    SESSION: visible only within this conversation
    """

    GLOBAL = "global"
    ORGANIZATION = "organization"
    TEAM = "team"
    USER = "user"
    AGENT = "agent"
    SESSION = "session"


@dataclass
class Learning:
    """A self-improving correction learned from tool call patterns."""

    category: str = "general"
    trigger_keys: list[str] = field(default_factory=list)
    learning: str = ""
    tool_name: str = ""
    source_query: str = ""
    org_id: str = ""
    team_id: str = ""
    agent_id: str | None = None
    user_id: str | None = None
    scope: MemoryScope = MemoryScope.AGENT
    hit_count: int = 0
    status: str = "active"
    id: int | None = None


@dataclass
class Outcome:
    """The outcome of a completed request — tracks task completion rate."""

    request_id: str = ""
    task_type: str = ""
    model_used: str = ""
    provider: str = ""
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    success: bool = True
    error_type: str = ""
    response_time_ms: int = 0
    org_id: str = ""
    team_id: str = ""
    user_id: str = ""
    agent_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    charged_microchips: int = 0
    pricing_version: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class SkillMutation:
    """Record of a skill being rewritten from a promoted learning."""

    skill_name: str = ""
    learning_id: int = 0
    old_prompt_hash: str = ""
    new_prompt_hash: str = ""
    mutation_type: str = "system_prompt_update"
    org_id: str = ""
    team_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class EpisodicMemory:
    """A single episodic memory in the 7-tier weighted system."""

    memory_id: str = ""
    tier: MemoryTier = MemoryTier.OBSERVATION
    content: str = ""
    weight: float = 0.3
    org_id: str = ""
    team_id: str = ""
    agent_id: str | None = None
    user_id: str | None = None
    scope: MemoryScope = MemoryScope.AGENT
    source: str = ""
    context: dict[str, str] = field(default_factory=dict)
    reinforcement_count: int = 0
    contradiction_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted: bool = False


@dataclass(frozen=True)
class SessionCheckpoint:
    """Typed snapshot of working state for cross-session handoff (S1.3).

    Schema-compatible with the client-side checkpoint format written by the
    `/checkpoint-save` skill (S1.6). Frontmatter keys in the client Markdown
    map byte-for-byte onto these fields.

    Field notes:
    - `scope`: enum MemoryScope; SESSION is the typical value for ad-hoc handoffs,
      USER/AGENT for longer-lived resume points.
    - `source`: who wrote the checkpoint — `agent` (server-side strategy),
      `claude_code` (client-side skill), or `manual` (UI / admin upload).
    - Ordered lists (decisions/remaining/notes/failed_approaches) are tuples so
      the dataclass stays frozen and hashable.
    """

    checkpoint_id: str
    session_id: str
    agent_id: str | None
    user_id: str | None
    org_id: str
    team_id: str | None
    scope: MemoryScope
    branch: str | None
    summary: str
    decisions: tuple[str, ...]
    remaining: tuple[str, ...]
    notes: tuple[str, ...]
    failed_approaches: tuple[str, ...]
    created_at: datetime
    source: Literal["agent", "claude_code", "manual"]
