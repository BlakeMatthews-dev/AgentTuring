"""Context filter: extracts task-relevant messages from chat history.

Strips greetings, off-topic tangents, and noise. Keeps messages that
provide context for the task the specialist agent needs to handle.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that indicate non-task messages (greetings, small talk)
_NOISE_PATTERNS = [
    re.compile(r"^(hey|hi|hello|yo|sup|howdy)\b", re.IGNORECASE),
    re.compile(r"^(how are you|how's it going|what's up)\b", re.IGNORECASE),
    re.compile(r"^(thanks|thank you|thx|ty)\b", re.IGNORECASE),
    re.compile(r"^(ok|okay|sure|got it|cool|nice)\b", re.IGNORECASE),
    re.compile(r"^(good morning|good afternoon|good evening)\b", re.IGNORECASE),
    re.compile(r"^(bye|goodbye|see you|later)\b", re.IGNORECASE),
    re.compile(r"\b(weather|sports score|joke|fun fact)\b", re.IGNORECASE),
    re.compile(r"^(oh wait|never mind|nm|nvm)\b", re.IGNORECASE),
]

# Patterns that indicate task-relevant messages
_RELEVANCE_SIGNALS: dict[str, list[re.Pattern[str]]] = {
    "code": [
        re.compile(r"\b(function|class|module|file|import|error|bug|fix)\b", re.IGNORECASE),
        re.compile(r"\b(python|javascript|typescript|rust|go|java)\b", re.IGNORECASE),
        re.compile(
            r"\b(api|fastapi|flask|django|endpoint|database|query|schema|migration)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(test|pytest|mypy|ruff|lint|type)\b", re.IGNORECASE),
        re.compile(r"\b(auth|jwt|token|middleware|route|handler)\b", re.IGNORECASE),
        re.compile(r"\b(deploy|docker|kubernetes|container|pod)\b", re.IGNORECASE),
        re.compile(r"\b(sort|parse|validate|convert|transform|filter)\b", re.IGNORECASE),
        re.compile(r"\b(401|403|404|500|exception|traceback|stack trace)\b", re.IGNORECASE),
    ],
}


def _is_noise(content: str) -> bool:
    """Check if a message is noise (greeting, small talk, off-topic)."""
    content = content.strip()
    if len(content) < 5:  # noqa: PLR2004
        return True
    return any(p.search(content) for p in _NOISE_PATTERNS)


def _is_relevant(content: str, task_type: str) -> bool:
    """Check if a message is relevant to the task type."""
    signals = _RELEVANCE_SIGNALS.get(task_type, [])
    if not signals:
        return True  # no signals defined = keep everything
    return any(p.search(content) for p in signals)


def extract_task_context(
    messages: list[dict[str, Any]],
    task_type: str = "code",
) -> list[dict[str, Any]]:
    """Extract task-relevant messages from chat history.

    Rules:
    1. System messages always kept
    2. Last user message always kept (it's the trigger)
    3. Messages matching task relevance signals kept
    4. Noise (greetings, small talk, off-topic) stripped
    5. Assistant responses to kept messages are also kept
    """
    if not messages:
        return []

    result: list[dict[str, Any]] = []
    kept_indices: set[int] = set()

    # Always keep system messages
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            kept_indices.add(i)

    # Always keep the last user message
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            kept_indices.add(i)
            break

    # Check each user message for relevance
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        if i in kept_indices:
            continue

        content = msg.get("content", "")
        if _is_noise(content):
            continue
        if _is_relevant(content, task_type):
            kept_indices.add(i)
            # Also keep the assistant response that follows
            if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                kept_indices.add(i + 1)

    # Build filtered list preserving order
    for i in sorted(kept_indices):
        result.append(messages[i])

    return result
