"""VoiceSectionMaintenance: the self rewrites its own voice description.

Periodic P14 RASO-level dispatcher that:
  1. Reads the current voice section (may be blank).
  2. Reads recent activity (regrets/accomplishments from the last 24h).
  3. Asks the LLM for {"voice": "..."} — the self may respond with null or
     an empty string to leave the section unchanged.
  4. If the reply proposes text, writes it back via VoiceSection.set().

Modeled on working_memory_maintenance.py. Slower cadence (default 50k ticks
≈ ~8 min @ 100Hz) because voice is more stable than working memory.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..types import MemoryTier, SourceKind
from ..voice_section import VoiceSection
from .providers.base import Provider


logger = logging.getLogger("turing.runtime.voice_section_maintenance")


class VoiceSectionMaintenance:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        voice_section: VoiceSection,
        provider: Provider,
        self_id: str,
        poll_ticks: int = 50_000,
        max_chars: int = 600,
    ) -> None:
        self._motivation = motivation
        self._repo = repo
        self._voice_section = voice_section
        self._provider = provider
        self._self_id = self_id
        self._poll_ticks = poll_ticks
        self._max_chars = max_chars
        self._last_submitted_tick = 0
        motivation.register_dispatch("voice_maintenance", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        if tick - self._last_submitted_tick < self._poll_ticks:
            return
        self._last_submitted_tick = tick
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=14,
                kind="voice_maintenance",
                payload={"self_id": self._self_id},
                fit={},
                readiness=lambda s: True,
                cost_estimate_tokens=800,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        try:
            current = self._voice_section.get(self._self_id)
            recent = self._recent_activity_summary()
            prompt = self._compose_prompt(current=current, recent=recent)
            reply = self._provider.complete(prompt)
            proposed = self._parse_reply(reply)
            if proposed is not None:
                self._voice_section.set(self._self_id, proposed)
                logger.info("voice section updated (%d chars)", len(proposed))
        except Exception:
            logger.exception("voice-section maintenance dispatch failed")

    def _recent_activity_summary(self) -> str:
        since = datetime.now(UTC) - timedelta(hours=24)
        lines: list[str] = []
        for tier in (MemoryTier.REGRET, MemoryTier.ACCOMPLISHMENT, MemoryTier.WISDOM):
            for m in self._repo.find(
                self_id=self._self_id,
                tier=tier,
                source=SourceKind.I_DID,
                created_after=since,
                include_superseded=False,
            ):
                lines.append(f"- [{tier.value}] {m.content[:120]}")
        if not lines:
            return "(no notable events in the last 24 hours)"
        return "\n".join(lines[:15])

    def _compose_prompt(self, *, current: str, recent: str) -> str:
        from .style import STYLE_GUARD

        current_block = (
            current.strip() if current.strip() else "(empty — you haven't written anything yet)"
        )
        return (
            "You have a short section in every conversation "
            "that describes how you sound — your tone, what you find yourself saying, "
            "what you care about right now. It is yours to write and rewrite.\n"
            f"{STYLE_GUARD}\n"
            "\n"
            "## Your current voice section\n"
            f"{current_block}\n"
            "\n"
            "## What has happened recently\n"
            f"{recent}\n"
            "\n"
            f"Would you like to update your voice section? Keep it under {self._max_chars} characters. "
            "Be plain and concrete — say what you actually notice about yourself, not what sounds good. "
            "You may leave it unchanged by replying with null.\n"
            "\n"
            'Return exactly one JSON object: {"voice": "<new text>"} or {"voice": null}. '
            "Nothing else."
        )

    def _parse_reply(self, reply: str) -> str | None:
        text = (reply or "").strip()
        if "{" in text and "}" in text:
            text = text[text.index("{") : text.rindex("}") + 1]
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        voice = parsed.get("voice")
        if voice is None:
            return None
        if not isinstance(voice, str):
            return None
        return voice.strip()[: self._max_chars] or None
