"""Journal: render the self's internal life to disk.

The Conduit's autonoetic activity (durable memory writes, daydream sessions,
dream sessions, AFFIRMATION commitments, REGRETs, ACCOMPLISHMENTs, WISDOM)
is internal by default. The Journal polls on a cadence and writes a
human-readable narrative + per-event markdown so an operator can actually
see what the self is doing.

Two outputs:

    <journal_dir>/narrative.md   — chronological diary, append-only
    <journal_dir>/identity.md    — current WISDOM, rewritten as it changes
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..repo import Repo
from ..types import EpisodicMemory, MemoryTier, SourceKind


logger = logging.getLogger("turing.runtime.journal")


DEFAULT_JOURNAL_POLL_TICKS: int = 200
_JOURNAL_TIERS: list[tuple[MemoryTier, str]] = [
    (MemoryTier.REGRET, "regret"),
    (MemoryTier.ACCOMPLISHMENT, "accomplishment"),
    (MemoryTier.AFFIRMATION, "commitment"),
    (MemoryTier.WISDOM, "wisdom"),
]


class Journal:
    """Polls the repo on a cadence; writes new significant events to disk."""

    def __init__(
        self,
        *,
        repo: Repo,
        self_id: str,
        journal_dir: str | Path,
        poll_ticks: int = DEFAULT_JOURNAL_POLL_TICKS,
    ) -> None:
        self._repo = repo
        self._self_id = self_id
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._narrative = self._dir / "narrative.md"
        self._identity = self._dir / "identity.md"
        self._poll_ticks = poll_ticks
        self._last_seen: datetime = datetime.now(UTC)
        self._wisdom_signature: str | None = None
        self._init_narrative()
        self._refresh_identity()

    # ---- Reactor hook

    def on_tick(self, tick: int) -> None:
        if tick % self._poll_ticks != 0:
            return
        try:
            self._poll_and_write()
        except Exception:
            logger.exception("journal poll failed")

    # ---- Setup

    def _init_narrative(self) -> None:
        if not self._narrative.exists():
            self._narrative.write_text(
                f"# Tess — narrative\n\n"
                f"_self_id: `{self._self_id}`_  \n"
                f"_started: {datetime.now(UTC).isoformat()}_\n\n"
                f"---\n\n"
            )

    # ---- Polling

    def _poll_and_write(self) -> None:
        cutoff = self._last_seen
        new_entries = self._collect_entries_since(cutoff)
        if not new_entries:
            self._refresh_identity()
            return

        with self._narrative.open("a", encoding="utf-8") as f:
            for entry in new_entries:
                f.write(entry)
                f.write("\n")

        self._last_seen = max(
            (datetime.fromisoformat(e_meta) for e_meta in self._extract_timestamps(new_entries)),
            default=cutoff,
        )
        self._refresh_identity()

    def _extract_timestamps(self, entries: list[str]) -> list[str]:
        out: list[str] = []
        for entry in entries:
            for line in entry.splitlines():
                line = line.strip()
                if line.startswith("## "):
                    # "## 2026-04-19T03:45:00+00:00 — ..."
                    parts = line[3:].split(" — ", 1)
                    out.append(parts[0])
                    break
        return out

    def _collect_entries_since(self, cutoff: datetime) -> list[str]:
        entries: list[tuple[datetime, str]] = []

        durable = []
        for tier, label in _JOURNAL_TIERS:
            for m in self._repo.find(
                self_id=self._self_id,
                tier=tier,
                source=SourceKind.I_DID,
                created_after=cutoff,
                include_superseded=True,
            ):
                durable.append((m.created_at, _render_durable(m, label)))

        # Episodic LESSONs (non-durable but significant).
        lessons = []
        for m in self._repo.find(
            self_id=self._self_id,
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
            created_after=cutoff,
        ):
            lessons.append((m.created_at, _render_durable(m, "lesson")))

        # Dream session markers.
        dreams = []
        for m in self._repo.find(
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            created_after=cutoff,
        ):
            if "dream session" in m.content and (
                "completed" in m.content or "truncated" in m.content
            ):
                dreams.append((m.created_at, _render_dream(m)))

        entries = durable + lessons + dreams
        entries.sort(key=lambda e: e[0])
        return [text for _, text in entries]

    # ---- Identity (current WISDOM)

    def _refresh_identity(self) -> None:
        wisdom = sorted(
            self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.WISDOM,
                source=SourceKind.I_DID,
                include_superseded=False,
            ),
            key=lambda m: m.created_at,
        )
        signature = "|".join(w.memory_id for w in wisdom)
        if signature == self._wisdom_signature:
            return
        self._wisdom_signature = signature

        lines = [
            "# Identity\n",
            f"_self_id: `{self._self_id}`_  \n",
            f"_updated: {datetime.now(UTC).isoformat()}_\n\n",
        ]
        if not wisdom:
            lines.append("_(no WISDOM yet — the self has not consolidated identity claims)_\n")
        else:
            lines.append("## Things I have come to know about myself\n\n")
            for w in wisdom:
                lineage = w.context.get("supersedes_via_lineage") if w.context else []
                n = len(lineage) if isinstance(lineage, list) else 0
                lines.append(f"- **{w.content}**  \n")
                lines.append(
                    f"  _from {n} contributing experiences; recorded {w.created_at.isoformat()}_\n"
                )
        self._identity.write_text("".join(lines))


# --- Rendering helpers ---------------------------------------------------


def _render_durable(m: EpisodicMemory, label: str) -> str:
    timestamp = m.created_at.isoformat()
    weight_str = f"weight {m.weight:.2f}"
    affect_str = f"affect {m.affect:+.2f}" if m.affect else ""
    intent_str = f"intent: `{m.intent_at_time}`" if m.intent_at_time else ""
    meta = "  ·  ".join(filter(None, [weight_str, affect_str, intent_str]))
    body = f"## {timestamp} — {label}\n\n{m.content}\n\n_{meta}_\n"
    return body


def _render_dream(m: EpisodicMemory) -> str:
    timestamp = m.created_at.isoformat()
    return f"## {timestamp} — dream session\n\n{m.content}\n"
