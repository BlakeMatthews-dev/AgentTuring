"""Intent classification types.

An Intent represents the classified purpose, complexity, and priority
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
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    min_tier: str = "small"
    max_tier: str | None = None
    preferred_strengths: tuple[str, ...] = ("chat",)
    classified_by: str = "keywords"
    keyword_score: float = 0.0
    user_text: str = ""
    multi_intents: tuple[str, ...] = ()
