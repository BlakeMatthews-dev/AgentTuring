"""WorkingMemoryMaintenance: the self edits its own working memory.

Periodic P13 RASO-level dispatcher that:
  1. Reads current working memory.
  2. Reads recent activity (recent durable memories, recent chat).
  3. Asks the LLM to propose updates as JSON: {add: [...], remove: [entry_id, ...]}.
  4. Applies the diff, subject to capacity bounds.

The self is the only writer; the operator's base prompt is elsewhere and
never mutated here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..types import MemoryTier, SourceKind
from ..working_memory import WorkingMemory
from .providers.base import Provider


logger = logging.getLogger("turing.runtime.working_memory_maintenance")


DEFAULT_WM_MAINTENANCE_TICKS: int = 12_000  # every ~2 min at 100Hz


@dataclass(frozen=True)
class WMUpdate:
    adds: list[tuple[str, float]]
    removes: list[str]


class WorkingMemoryMaintenance:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        working_memory: WorkingMemory,
        provider: Provider,
        self_id: str,
        poll_ticks: int = DEFAULT_WM_MAINTENANCE_TICKS,
    ) -> None:
        self._motivation = motivation
        self._repo = repo
        self._working_memory = working_memory
        self._provider = provider
        self._self_id = self_id
        self._poll_ticks = poll_ticks
        self._last_submitted_tick = 0
        motivation.register_dispatch("wm_maintenance", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        if tick - self._last_submitted_tick < self._poll_ticks:
            return
        self._last_submitted_tick = tick
        self._motivation.insert(self._build_candidate())

    def _build_candidate(self) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=13,
            kind="wm_maintenance",
            payload={"self_id": self._self_id},
            fit={},
            readiness=lambda s: True,
            cost_estimate_tokens=1_200,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        try:
            current = self._working_memory.entries(self._self_id)
            recent = self._recent_activity_summary()
            prompt = self._compose_prompt(current=current, recent=recent)
            reply = self._provider.complete(prompt)
            update = self._parse_reply(reply)
            self._apply_update(current, update)
        except Exception:
            logger.exception("working-memory maintenance dispatch failed")

    def _recent_activity_summary(self) -> str:
        """Compact list of what's happened in the last window."""
        since = datetime.now(UTC) - timedelta(hours=1)
        lines: list[str] = []
        for tier in (
            MemoryTier.REGRET,
            MemoryTier.ACCOMPLISHMENT,
            MemoryTier.AFFIRMATION,
            MemoryTier.WISDOM,
        ):
            for m in self._repo.find(
                self_id=self._self_id,
                tier=tier,
                source=SourceKind.I_DID,
                created_after=since,
                include_superseded=False,
            ):
                lines.append(f"- [{tier.value}] {m.content[:120]}")
        if not lines:
            return "(no new durable memories in the last hour)"
        return "\n".join(lines[:20])

    def _compose_prompt(self, *, current: list, recent: str) -> str:
        from .style import STYLE_GUARD

        if current:
            current_block = "\n".join(
                f"- [id:{e.entry_id} priority:{e.priority:.2f}] {e.content}" for e in current
            )
        else:
            current_block = "(empty)"
        return (
            "You are maintaining your own working memory.\n"
            "Working memory is your scratch space — what you want to keep\n"
            "front-of-mind across conversations and routings. Be selective.\n"
            f"{STYLE_GUARD}\n"
            "\n"
            "## Current working memory\n"
            f"{current_block}\n"
            "\n"
            "## Recent durable memories (last hour)\n"
            f"{recent}\n"
            "\n"
            "Return a single JSON object matching this schema exactly:\n"
            '  {"add": [{"content": "<string>", "priority": <0..1>}, ...],\n'
            '   "remove": ["<entry_id>", ...]}\n'
            "Keep the total entries under 10. Only respond with the JSON.\n"
        )

    def _parse_reply(self, reply: str) -> WMUpdate:
        text = (reply or "").strip()
        if "{" in text and "}" in text:
            text = text[text.index("{") : text.rindex("}") + 1]
        try:
            parsed = json.loads(text)
        except Exception:
            return WMUpdate(adds=[], removes=[])
        adds: list[tuple[str, float]] = []
        for item in parsed.get("add") or []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "") or "").strip()
            priority = item.get("priority", 0.5)
            try:
                priority_f = float(priority)
            except (TypeError, ValueError):
                priority_f = 0.5
            priority_f = max(0.0, min(1.0, priority_f))
            if content:
                adds.append((content, priority_f))
        removes: list[str] = []
        for eid in parsed.get("remove") or []:
            if isinstance(eid, str) and eid:
                removes.append(eid)
        return WMUpdate(adds=adds, removes=removes)

    def _apply_update(self, current: list, update: WMUpdate) -> None:
        for entry_id in update.removes:
            self._working_memory.remove(self._self_id, entry_id)
        existing_content = {e.content[:60].lower() for e in current}
        for content, priority in update.adds:
            key = content[:60].lower()
            if key in existing_content:
                logger.debug("skipping duplicate wm entry: %r", content[:40])
                continue
            try:
                self._working_memory.add(self._self_id, content, priority=priority)
                existing_content.add(key)
            except Exception:
                logger.exception("wm add failed for %r", content[:40])
