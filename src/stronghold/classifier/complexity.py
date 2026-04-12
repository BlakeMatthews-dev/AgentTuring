"""Complexity estimation and priority inference."""

from __future__ import annotations

import re

from stronghold.types.intent import TIER_ORDER

_FILLER_WORDS = frozenset(
    {
        "the",
        "my",
        "a",
        "an",
        "please",
        "hey",
        "ok",
        "okay",
        "yo",
        "dude",
        "can",
        "you",
        "could",
        "would",
        "just",
    }
)

_SMART_HOME_SIMPLE_MAX_WORDS = 3

_COMPLEX_SIGNALS = [
    r"\b(step by step|detailed|thorough|comprehensive|in-depth)\b",
    r"\b(multiple|several|all|every|each)\b.*\b(files?|functions?|components?)\b",
    r"\b(refactor|architect|design|optimize|migrate)\b",
    r"\b(compare|contrast|pros and cons|trade.?offs?)\b",
]


def estimate_complexity(text: str, task_type: str) -> str:
    """Estimate task complexity from message text."""
    word_count = len(text.split())
    if word_count < 15:
        return "simple"
    if word_count > 200:
        return "complex"

    complex_score = sum(1 for p in _COMPLEX_SIGNALS if re.search(p, text, re.IGNORECASE))
    if complex_score >= 2:
        return "complex"
    if complex_score >= 1 or word_count > 80:
        return "moderate"
    if task_type in ("code", "reasoning"):
        return "moderate"
    return "simple"


def infer_priority(user_text: str) -> str:
    """Infer priority tier from urgency keywords.

    Returns a 6-tier priority value per ADR-K8S-014:
      P0 = chat-critical, P1 = chat-tools, P2 = user-missions,
      P3 = backend-support, P4 = quartermaster, P5 = builders.
    """
    text = user_text.lower()
    if any(s in text for s in ["urgent", "critical", "emergency", "asap", "broken", "down"]):
        return "P0"
    if any(s in text for s in ["important", "priority", "deadline", "client", "demo"]):
        return "P1"
    if any(s in text for s in ["just curious", "when you get a chance", "no rush", "fyi"]):
        return "P4"
    return "P2"


def automation_min_tier(user_text: str, base_min_tier: str) -> str:
    """Determine min_tier for automation based on command complexity.

    Short commands (<=3 meaningful words) can use small/fast models.
    Longer commands need medium+ for entity resolution.
    """
    words = user_text.lower().split()
    meaningful = [w for w in words if w not in _FILLER_WORDS]
    if len(meaningful) <= _SMART_HOME_SIMPLE_MAX_WORDS:
        return base_min_tier
    if TIER_ORDER.get(base_min_tier, 0) < TIER_ORDER["medium"]:
        return "medium"
    return base_min_tier
