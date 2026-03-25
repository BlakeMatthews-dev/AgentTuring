"""Keyword-based intent classification.

Three layers:
1. Strong indicators (phrase matching, +3.0 per match)
2. Config keywords (word boundary matching, +1.0 per match)
3. Negative signals (suppress false positives, -2.0 per match)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.config import TaskTypeConfig

STRONG_INDICATORS: dict[str, list[str]] = {
    "code": [
        "write a function",
        "write a script",
        "write code",
        "fix the bug",
        "debug this",
        "refactor",
        "implement this",
        "pull request",
        "syntax error",
        "stack trace",
        "traceback",
        "unit test",
        "dockerfile",
        "docker compose",
    ],
    "automation": [
        "turn on the",
        "turn off the",
        "turn on my",
        "turn off my",
        "turn it on",
        "turn it off",
        "switch on",
        "switch off",
        "set brightness",
        "dim the",
        "set temperature",
        "chore",
        "chores",
        "allowance",
        "overdue chores",
        "is the fan",
        "is the light",
        "lock the",
        "unlock the",
    ],
    "creative": [
        "write a story",
        "write a poem",
        "write me a",
        "creative writing",
        "brainstorm ideas",
    ],
    "reasoning": [
        "step by step",
        "prove that",
        "derive the",
        "pros and cons",
        "compare and contrast",
        "analyze this",
        "evaluate the",
        "think through",
    ],
    "image_gen": [
        "generate an image",
        "create an image",
        "draw me",
        "generate a picture",
        "create a logo",
    ],
    "search": [
        "search for",
        "look up",
        "search the web",
        "google",
        "find information about",
        "latest news about",
    ],
}

NEGATIVE_SIGNALS: dict[str, list[str]] = {
    "code": [
        "what is the",
        "who is the",
        "where is the",
        "when is the",
        "capital of",
        "president of",
        "history of",
        "meaning of",
        "tell me about",
        "how does a",
    ],
    "automation": [
        "what's the point",
        "good point",
        "point of view",
        "switching topics",
        "temperature of the sun",
    ],
}


def score_keywords(
    user_text: str,
    task_types: dict[str, TaskTypeConfig],
) -> dict[str, float]:
    """Score each task type by keyword matching.

    Returns dict of {task_type: score}. Higher = better match.
    """
    text_lower = user_text.lower()
    scores: dict[str, float] = {}

    for task_name, task_cfg in task_types.items():
        score = 0.0

        # Strong indicators: word-boundary-padded matching
        for phrase in STRONG_INDICATORS.get(task_name, []):
            padded_phrase = " " + phrase + " "
            padded_text = " " + text_lower + " "
            if padded_phrase in padded_text:
                score += 3.0

        # Config keywords: word boundary regex
        for kw in task_cfg.keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, text_lower):
                score += 1.0

        # Negative signals
        for neg in NEGATIVE_SIGNALS.get(task_name, []):
            if neg in text_lower:
                score -= 2.0

        if score > 0:
            scores[task_name] = score

    return scores
