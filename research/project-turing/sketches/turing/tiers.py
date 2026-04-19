"""Weight bounds and inheritance priority per tier. See specs/tiers.md."""

from __future__ import annotations

from .types import MemoryTier

WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION: (0.1, 0.5),
    MemoryTier.HYPOTHESIS: (0.2, 0.6),
    MemoryTier.OPINION: (0.3, 0.8),
    MemoryTier.LESSON: (0.5, 0.9),
    MemoryTier.REGRET: (0.6, 1.0),
    MemoryTier.ACCOMPLISHMENT: (0.6, 1.0),
    MemoryTier.AFFIRMATION: (0.6, 1.0),
    MemoryTier.WISDOM: (0.9, 1.0),
}


INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION: 1,
    MemoryTier.HYPOTHESIS: 2,
    MemoryTier.OPINION: 3,
    MemoryTier.LESSON: 4,
    MemoryTier.REGRET: 5,
    MemoryTier.ACCOMPLISHMENT: 5,
    MemoryTier.AFFIRMATION: 5,
    MemoryTier.WISDOM: 6,
}


def clamp_weight(tier: MemoryTier, proposed: float) -> float:
    lo, hi = WEIGHT_BOUNDS[tier]
    return max(lo, min(hi, proposed))
