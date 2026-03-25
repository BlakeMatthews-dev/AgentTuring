"""Session summarization: expiring sessions → episodic memory bridge.

When a session expires or is cleaned up, the conversation is summarized
by an LLM and stored as a low-weight OBSERVATION in episodic memory.
This preserves context without bloating active session storage.

Session ID format: "{org_id}/{team_id}/{user_id}:{session_name}"
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier

if TYPE_CHECKING:
    from stronghold.memory.episodic.store import InMemoryEpisodicStore
    from stronghold.protocols.llm import LLMClient

logger = logging.getLogger("stronghold.sessions.summarizer")

_SUMMARIZE_PROMPT = (
    "Summarize this conversation in 2-3 sentences. "
    "Note any user preferences, decisions made, or key facts learned.\n\n"
)


class SessionSummarizer:
    """Summarizes expiring sessions and bridges them to episodic memory."""

    def __init__(
        self,
        llm: LLMClient,
        episodic_store: InMemoryEpisodicStore,
        model: str = "auto",
    ) -> None:
        self._llm = llm
        self._episodic_store = episodic_store
        self._model = model

    async def summarize_and_bridge(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        *,
        org_id: str = "",
        team_id: str = "",
        user_id: str = "",
        agent_id: str | None = None,
    ) -> EpisodicMemory | None:
        """Summarize a conversation and store as episodic memory.

        Returns the created EpisodicMemory, or None if the session was
        too short or summarization failed.
        """
        # Skip very short sessions (nothing worth remembering)
        content_messages = [m for m in messages if m.get("content", "").strip()]
        if len(content_messages) < 3:  # noqa: PLR2004
            return None

        # Build conversation text for the LLM
        conversation_lines = []
        for msg in content_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]  # Truncate long messages
            conversation_lines.append(f"{role}: {content}")

        conversation_text = "\n".join(conversation_lines)
        prompt = _SUMMARIZE_PROMPT + conversation_text

        # Call LLM for summary
        summary = await self._call_llm(prompt)
        if not summary:
            return None

        # Parse identity from session_id if not provided
        if not user_id:
            parsed = self._parse_session_id(session_id)
            org_id = org_id or parsed.get("org_id", "")
            team_id = team_id or parsed.get("team_id", "")
            user_id = parsed.get("user_id", "")

        # Create episodic memory
        memory = EpisodicMemory(
            memory_id=str(uuid.uuid4()),
            tier=MemoryTier.OBSERVATION,
            content=summary,
            weight=0.2,  # Low weight — initial observation
            org_id=org_id,
            team_id=team_id,
            agent_id=agent_id,
            user_id=user_id,
            scope=MemoryScope.USER if user_id else MemoryScope.TEAM,
            source=f"session_summary:{session_id}",
            context={"session_id": session_id},
        )

        await self._episodic_store.store(memory)
        logger.info(
            "Session %s summarized → episodic %s (user=%s)",
            session_id,
            memory.memory_id,
            user_id,
        )
        return memory

    async def _call_llm(self, prompt: str) -> str | None:
        """Call LLM for summarization."""
        try:
            result: dict[str, Any] = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=150,
                temperature=0.0,
            )
            choices = result.get("choices", [])
            if choices:
                return str(choices[0].get("message", {}).get("content", ""))
        except Exception as e:
            logger.warning("Session summarization LLM call failed: %s", e)
        return None

    @staticmethod
    def _parse_session_id(session_id: str) -> dict[str, str]:
        """Parse identity from session_id format: 'org/team/user:session_name'.

        Also handles simpler formats like 'user:session' or just 'session'.
        """
        result: dict[str, str] = {}
        # Split on colon to separate identity from session name
        parts = session_id.split(":", 1)
        identity = parts[0]

        # Split identity on slashes: org/team/user
        segments = identity.split("/")
        if len(segments) >= 3:  # noqa: PLR2004
            result["org_id"] = segments[0]
            result["team_id"] = segments[1]
            result["user_id"] = segments[2]
        elif len(segments) == 2:  # noqa: PLR2004
            result["team_id"] = segments[0]
            result["user_id"] = segments[1]
        elif len(segments) == 1 and segments[0]:
            result["user_id"] = segments[0]

        return result
