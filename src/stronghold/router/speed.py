"""Task-type-aware speed bonuses.

Speed bonus adjusts quality: adjusted_quality = quality * (1 + weight * norm_speed)
- automation: 0.25 (fast response critical for voice)
- chat: 0.15 (snappy feels good)
- code: 0.0 (quality is everything)
"""

from __future__ import annotations

SPEED_WEIGHTS: dict[str, float] = {
    "automation": 0.25,
    "chat": 0.15,
    "summarize": 0.10,
    "search": 0.10,
    "creative": 0.05,
    "code": 0.0,
    "reasoning": 0.0,
    "trading": 0.0,
    "image_gen": 0.0,
    "embedding": 0.0,
}

_MAX_SPEED: float = 2000.0  # 2000 tok/s = normalized speed of 1.0


def compute_speed_bonus(task_type: str, speed: int) -> float:
    """Compute speed bonus for a task type and model speed.

    Returns a multiplier delta (0.0 means no bonus).
    """
    weight = SPEED_WEIGHTS.get(task_type, 0.0)
    if weight == 0.0:
        return 0.0
    norm_speed = min(1.0, speed / _MAX_SPEED)
    return weight * norm_speed
