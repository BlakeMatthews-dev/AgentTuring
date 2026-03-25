"""Multi-intent detection for compound requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.classifier.keyword import STRONG_INDICATORS

if TYPE_CHECKING:
    from stronghold.types.config import TaskTypeConfig


def detect_multi_intent(
    user_text: str,
    task_types: dict[str, TaskTypeConfig],
) -> list[str]:
    """Detect if a message contains multiple distinct intents.

    Returns list of task_type strings if compound, else empty.
    """
    text_lower = user_text.lower()

    # Split on common conjunctions
    splitters = [" and then ", " and also ", " and ", " also ", ". also ", ". then "]
    parts = [text_lower]
    for splitter in splitters:
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(splitter))
        parts = new_parts

    # Need at least 2 meaningful parts
    parts = [p.strip() for p in parts if len(p.strip()) > 5]
    if len(parts) < 2:
        return []

    # Classify each part independently
    seen_types: list[str] = []
    for part in parts:
        best_type: str | None = None
        best_score = 0.0
        for task_name in STRONG_INDICATORS:
            for phrase in STRONG_INDICATORS[task_name]:
                padded = " " + phrase + " "
                if padded in " " + part + " " and best_score < 3.0:
                    best_score = 3.0
                    best_type = task_name
                    break

        # Also check config keywords
        if best_type is None:
            for task_name, task_cfg in task_types.items():
                for kw in task_cfg.keywords:
                    if kw in part and task_name not in seen_types:
                        best_type = task_name
                        break
                if best_type:
                    break

        if best_type and best_type not in seen_types:
            seen_types.append(best_type)

    return seen_types if len(seen_types) >= 2 else []
