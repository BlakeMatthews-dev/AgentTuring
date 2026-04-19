"""Actor: bridges internal durable-memory events to outward-facing tool calls.

Polls durable memory on a cadence (like the Journal). For each new
significant memory, if a relevant Tool is registered, invoke it. Examples:

- New WISDOM → ObsidianWriter writes a vault note
- New AFFIRMATION (commitment) → ObsidianWriter writes a "I now commit to X" note
- New REGRET / ACCOMPLISHMENT → ObsidianWriter writes a brief

If no tools are registered for a category, the Actor silently no-ops on it
— exactly like the Journal continues to render to disk.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..repo import Repo
from ..types import EpisodicMemory, MemoryTier, SourceKind
from .tools.base import ToolMode, ToolNotPermitted, ToolRegistry


logger = logging.getLogger("turing.runtime.actor")


DEFAULT_ACTOR_POLL_TICKS: int = 200


class Actor:
    def __init__(
        self,
        *,
        repo: Repo,
        self_id: str,
        registry: ToolRegistry,
        poll_ticks: int = DEFAULT_ACTOR_POLL_TICKS,
    ) -> None:
        self._repo = repo
        self._self_id = self_id
        self._registry = registry
        self._poll_ticks = poll_ticks
        self._last_seen: datetime = datetime.now(UTC)

    def on_tick(self, tick: int) -> None:
        if tick % self._poll_ticks != 0:
            return
        try:
            self._poll_and_act()
        except Exception:
            logger.exception("actor poll failed")

    def _poll_and_act(self) -> None:
        cutoff = self._last_seen
        events = self._collect_events_since(cutoff)
        if not events:
            return
        for memory in events:
            self._handle(memory)
        self._last_seen = max(m.created_at for m in events)

    def _collect_events_since(
        self, cutoff: datetime
    ) -> list[EpisodicMemory]:
        out: list[EpisodicMemory] = []
        for tier in (
            MemoryTier.WISDOM,
            MemoryTier.REGRET,
            MemoryTier.ACCOMPLISHMENT,
            MemoryTier.AFFIRMATION,
        ):
            for m in self._repo.find(
                self_id=self._self_id,
                tier=tier,
                source=SourceKind.I_DID,
                created_after=cutoff,
                include_superseded=False,
            ):
                out.append(m)
        out.sort(key=lambda m: m.created_at)
        return out

    def _handle(self, memory: EpisodicMemory) -> None:
        if "obsidian_writer" in self._registry.names():
            self._write_obsidian(memory)

    def _write_obsidian(self, memory: EpisodicMemory) -> None:
        title, kind = _title_and_kind_for(memory)
        body = _body_for(memory)
        try:
            self._registry.invoke(
                "obsidian_writer",
                title=title,
                content=body,
                kind=kind,
                tags=[memory.tier.value, "turing"],
                front_matter={
                    "memory_id": memory.memory_id,
                    "self_id": memory.self_id,
                    "tier": memory.tier.value,
                    "intent": memory.intent_at_time or "",
                    "affect": memory.affect,
                    "weight": memory.weight,
                },
            )
        except ToolNotPermitted:
            pass
        except Exception:
            logger.exception("obsidian write failed for %s", memory.memory_id)


def _title_and_kind_for(m: EpisodicMemory) -> tuple[str, str]:
    tier = m.tier.value
    snippet = m.content[:60]
    if m.tier == MemoryTier.WISDOM:
        return f"WISDOM — {snippet}", "wisdom"
    if m.tier == MemoryTier.REGRET:
        return f"Regret — {snippet}", "regret"
    if m.tier == MemoryTier.ACCOMPLISHMENT:
        return f"Accomplishment — {snippet}", "accomplishment"
    if m.tier == MemoryTier.AFFIRMATION:
        return f"Commitment — {snippet}", "affirmation"
    return snippet, tier


def _body_for(m: EpisodicMemory) -> str:
    parts: list[str] = [m.content, ""]
    if m.intent_at_time:
        parts.append(f"_intent_: `{m.intent_at_time}`")
    if m.affect:
        parts.append(f"_affect_: {m.affect:+.2f}")
    if m.surprise_delta:
        parts.append(f"_surprise_: {m.surprise_delta:.2f}")
    if m.context:
        lineage = m.context.get("supersedes_via_lineage")
        if isinstance(lineage, list) and lineage:
            parts.append(f"_lineage_: {len(lineage)} contributing memories")
    return "\n".join(parts)
