"""7-tier episodic memory with enforced weight bounds.

Key design: REGRET weight cannot drop below 0.6 — structurally unforgettable.
"""

from __future__ import annotations

from stronghold.types.memory import (
    REINFORCE_DELTA,
    WEIGHT_BOUNDS,
    EpisodicMemory,
    MemoryTier,
)


def clamp_weight(tier: MemoryTier, proposed: float) -> float:
    """Clamp weight to tier bounds."""
    bounds = WEIGHT_BOUNDS.get(tier, (0.1, 1.0))
    return max(bounds[0], min(bounds[1], proposed))


def reinforce(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory:
    """Reinforce a memory — increase weight, clamped to tier ceiling."""
    new_weight = clamp_weight(memory.tier, memory.weight + delta)
    return EpisodicMemory(
        memory_id=memory.memory_id,
        tier=memory.tier,
        content=memory.content,
        weight=new_weight,
        agent_id=memory.agent_id,
        user_id=memory.user_id,
        org_id=memory.org_id,
        team_id=memory.team_id,
        scope=memory.scope,
        source=memory.source,
        context=memory.context,
        reinforcement_count=memory.reinforcement_count + 1,
        contradiction_count=memory.contradiction_count,
        created_at=memory.created_at,
        last_accessed_at=memory.last_accessed_at,
        deleted=memory.deleted,
    )


def decay(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory:
    """Decay a memory — decrease weight, clamped to tier floor."""
    new_weight = clamp_weight(memory.tier, memory.weight - delta)
    return EpisodicMemory(
        memory_id=memory.memory_id,
        tier=memory.tier,
        content=memory.content,
        weight=new_weight,
        agent_id=memory.agent_id,
        user_id=memory.user_id,
        org_id=memory.org_id,
        team_id=memory.team_id,
        scope=memory.scope,
        source=memory.source,
        context=memory.context,
        reinforcement_count=memory.reinforcement_count,
        contradiction_count=memory.contradiction_count + 1,
        created_at=memory.created_at,
        last_accessed_at=memory.last_accessed_at,
        deleted=memory.deleted,
    )
