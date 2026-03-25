"""LLM-based classification fallback for ambiguous queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient

logger = logging.getLogger("stronghold.classifier.llm_fallback")

_VALID_CATEGORIES = frozenset(
    {
        "chat",
        "code",
        "automation",
        "trading",
        "creative",
        "reasoning",
        "image_gen",
        "search",
        "summarize",
        "embedding",
    }
)

_LLM_CLASSIFY_PROMPT = """Classify this user message into exactly ONE category.

Categories:
- chat: General conversation, greetings, trivia
- code: Programming, debugging, writing code
- automation: Controlling devices, home automation
- creative: Writing stories, poems, brainstorming
- reasoning: Complex analysis, math, logic
- image_gen: Creating or generating images
- search: Web search, looking up facts
- summarize: Summarizing text or documents

Respond with ONLY the category name, nothing else.

User message: {user_text}"""


async def llm_classify(
    user_text: str,
    llm_client: LLMClient,
    model: str = "auto",
) -> str | None:
    """Call a fast LLM to classify the user's message."""
    prompt = _LLM_CLASSIFY_PROMPT.format(user_text=user_text[:200])

    try:
        resp: dict[str, Any] = await llm_client.complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=10,
            temperature=0.0,
        )
        content: str = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content or not content.strip():
            return None

        text = content.strip().lower()
        words = text.split()
        first_word = words[0] if words else ""
        if first_word in _VALID_CATEGORIES:
            return first_word
        for cat in _VALID_CATEGORIES:
            if cat in text:
                return cat
    except Exception:  # noqa: BLE001
        logger.debug("LLM classification failed for '%s'", user_text[:60], exc_info=True)

    return None
