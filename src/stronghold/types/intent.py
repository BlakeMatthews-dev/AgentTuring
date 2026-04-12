"""Intent classification types.

An Intent represents the classified purpose, complexity, and tier
of a user's message. Produced by the classifier, consumed by the router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Tier ordering for model selection filtering
TIER_ORDER: dict[str, int] = {
    "small": 0,
    "medium": 1,
    "large": 2,
    "frontier": 3,
}


@dataclass(frozen=True)
class Intent:
    """Classified intent of a user message."""

    task_type: str = "chat"
    complexity: Literal["simple", "moderate", "complex"] = "simple"
    tier: Literal["P0", "P1", "P2", "P3", "P4", "P5"] = "P2"
    min_tier: str = "small"
    max_tier: str | None = None
    preferred_strengths: tuple[str, ...] = ("chat",)
    classified_by: str = "keywords"
    keyword_score: float = 0.0
    user_text: str = ""
    multi_intents: tuple[str, ...] = ()
