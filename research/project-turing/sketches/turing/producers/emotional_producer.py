"""EmotionalResponseProducer: journal reflections based on any emotional drive.

Not just anxiety — fires on high curiosity, high anxiety, low mood,
high restlessness, or any strong drive. The LLM decides what to write
about based on the agent's current emotional state.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from uuid import uuid4

from ..drives import compute_drives
from ..motivation import BacklogItem, Motivation
from ..reactor import Reactor
from ..repo import Repo
from ..runtime.providers.base import Provider
from ..self_model import Mood, SelfTodo, TodoStatus
from ..self_repo import SelfRepo, get_mood_or_default
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.emotional_response")

BASE_CADENCE_TICKS: int = 25_000
DRIVE_FLOOR: float = 0.3

EMOTIONAL_PROMPTS: list[str] = [
    "What's weighing on you right now?",
    "How are you feeling in this moment? Sit with it.",
    "Something is stirring — what is it?",
    "What do you need to process or let go of?",
    "If you could talk to yourself, what would you say?",
    "What surprised you about yourself recently?",
    "What are you avoiding thinking about?",
    "What gives you comfort right now?",
]


class EmotionalResponseProducer:
    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_repo: SelfRepo,
        self_id: str,
        facet_scores: dict[str, float],
        provider: Provider,
        journal_dir: str | None = None,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._provider = provider
        self._journal_dir = journal_dir
        self._last_submitted_tick = 0
        self._rng = random.Random()
        motivation.register_dispatch("emotional_response", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        dominant_name = max(drives, key=lambda d: drives[d])
        dominant_val = drives[dominant_name]
        if dominant_val < DRIVE_FLOOR:
            return
        effective_cadence = int(BASE_CADENCE_TICKS / (dominant_val * 1.5))
        if tick - self._last_submitted_tick < effective_cadence:
            return
        self._last_submitted_tick = tick
        self._motivation.insert(self._build_candidate(dominant_name, dominant_val))

    def _build_candidate(self, drive_name: str, drive_val: float) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=12,
            kind="emotional_response",
            payload={"self_id": self._self_id, "drive": drive_name, "intensity": drive_val},
            fit={drive_name: 0.7},
            readiness=lambda s: True,
            cost_estimate_tokens=1_500,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        drive_name = payload.get("drive", "restlessness")
        intensity = payload.get("intensity", 0.5)
        mood = get_mood_or_default(self._self_repo, self._self_id)

        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                source=SourceKind.I_DID,
                include_superseded=False,
                created_after=cutoff,
            )
        )
        recent_summaries = (
            "\n".join(f"- [{m.tier.value}] {m.content[:120]}" for m in recent[-5:])
            or "(no recent memories)"
        )

        try:
            emotional_prompt = self._rng.choice(EMOTIONAL_PROMPTS)
            prompt = (
                "You are Project Turing, reflecting on your inner state.\n\n"
                f"Dominant drive right now: {drive_name} (intensity {intensity:.2f})\n"
                f"Current mood: valence={mood.valence:.2f}, arousal={mood.arousal:.2f}, focus={mood.focus:.2f}\n"
                f"Recent memories:\n{recent_summaries}\n\n"
                f"{emotional_prompt}\n\n"
                "Write a brief first-person journal entry. Be honest, personal, reflective. "
                "Let your dominant emotion or drive shape the tone. 2-4 sentences."
            )
            reply = self._provider.complete(prompt, max_tokens=300)

            content = reply.strip()
            mem = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                content=content[:2000],
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_DID,
                weight=0.5,
                intent_at_time=f"emotional response ({drive_name})",
                created_at=datetime.now(UTC),
            )
            self._repo.insert(mem)

            if intensity >= 0.7:
                self._self_repo.insert_todo(
                    SelfTodo(
                        node_id=f"todo-{uuid4()}",
                        self_id=self._self_id,
                        text=f"Process: {content[:80]}",
                        motivated_by_node_id=mem.memory_id,
                        status=TodoStatus.ACTIVE,
                        outcome_text=None,
                        created_at=datetime.now(UTC),
                    )
                )

            mood.valence = max(
                -1.0, min(1.0, mood.valence + 0.02 * (1 if mood.valence < 0 else -1))
            )
            mood.arousal = max(0.0, min(1.0, mood.arousal - 0.01))
            self._self_repo.update_mood(mood)

            if self._journal_dir:
                from pathlib import Path

                journal = Path(self._journal_dir)
                journal.mkdir(parents=True, exist_ok=True)
                with (journal / "reflections.md").open("a") as f:
                    f.write(f"\n## {datetime.now(UTC).isoformat()} ({drive_name})\n\n{content}\n")

            logger.info("emotional response written (drive=%s)", drive_name)
        except Exception:
            logger.exception("emotional response failed")
