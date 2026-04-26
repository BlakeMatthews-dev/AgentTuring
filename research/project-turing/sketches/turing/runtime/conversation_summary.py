"""ConversationSummaryCache: rolling topic+participant summary per conversation.

Refreshes every REFRESH_EVERY_N_TURNS turns via a short LLM call.
Renders as: "I have been talking to {participants} about {topics}, with the
most recent topic being {current_topic}."

Thread-safe; keyed by conversation_id; lives entirely in memory.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from .providers.base import Provider


logger = logging.getLogger("turing.runtime.conversation_summary")

REFRESH_EVERY_N_TURNS: int = 4


@dataclass
class ConvSummary:
    participants: list[str] = field(default_factory=lambda: ["the user"])
    topics: list[str] = field(default_factory=list)
    current_topic: str = ""
    turn_count_at_refresh: int = 0


class ConversationSummaryCache:
    def __init__(self, provider: Provider) -> None:
        self._provider = provider
        self._cache: dict[str, ConvSummary] = {}
        self._lock = threading.Lock()

    def maybe_refresh(
        self,
        conversation_id: str,
        history: list[dict[str, Any]],
        current_message: str,
    ) -> None:
        """Refresh the summary if enough new turns have accumulated."""
        total_turns = len(history) + 1  # +1 for the current message
        with self._lock:
            existing = self._cache.get(conversation_id)
            last_refresh = existing.turn_count_at_refresh if existing else 0

        if total_turns - last_refresh < REFRESH_EVERY_N_TURNS and existing is not None:
            return

        try:
            summary = self._generate(history, current_message)
        except Exception:
            logger.exception("conversation summary generation failed for %s", conversation_id)
            return

        with self._lock:
            self._cache[conversation_id] = summary

    def render(self, conversation_id: str) -> str | None:
        with self._lock:
            s = self._cache.get(conversation_id)
        if s is None or not s.topics:
            return None
        participants = " and ".join(s.participants) if s.participants else "the user"
        topics = ", ".join(s.topics)
        current = s.current_topic or (s.topics[-1] if s.topics else "")
        return (
            f"I have been talking to {participants} about {topics}, "
            f"with the most recent topic being {current}."
        )

    def _generate(
        self, history: list[dict[str, Any]], current_message: str
    ) -> ConvSummary:
        tail = list(history[-8:]) + [{"role": "user", "content": current_message}]
        convo_text = "\n".join(
            f'{t.get("role","user")}: {t.get("content","")[:300]}' for t in tail
        )
        prompt = (
            "Read this conversation excerpt and extract:\n"
            "1. The participants (use any names mentioned; default to 'the user' if no name)\n"
            "2. The main topics discussed, in the order they came up (3-6 short phrases)\n"
            "3. The most recent / current topic being discussed right now\n\n"
            "Respond with ONLY a single-line JSON object:\n"
            '{"participants": ["name", ...], "topics": ["topic1", ...], '
            '"current_topic": "latest topic"}\n\n'
            f"Conversation:\n{convo_text}"
        )
        reply = self._provider.complete(prompt, max_tokens=150)
        return _parse_summary(reply, turn_count=len(history) + 1)


def _parse_summary(reply: str, *, turn_count: int) -> ConvSummary:
    text = (reply or "").strip()
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return ConvSummary(turn_count_at_refresh=turn_count)
    participants = [str(p) for p in (parsed.get("participants") or ["the user"])]
    topics = [str(t) for t in (parsed.get("topics") or [])]
    current_topic = str(parsed.get("current_topic") or (topics[-1] if topics else ""))
    return ConvSummary(
        participants=participants,
        topics=topics,
        current_topic=current_topic,
        turn_count_at_refresh=turn_count,
    )
