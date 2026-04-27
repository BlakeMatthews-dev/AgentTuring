"""HobbyEngagementProducer: spend time on hobbies.

Spec 31d. Picks a hobby weighted by strength, produces creative work
or reflection depending on the hobby type.
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
from ..self_model import Mood
from ..self_repo import SelfRepo, get_mood_or_default
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.hobby")

BASE_CADENCE_TICKS: int = 60_000
RESTLESSNESS_FLOOR: float = 0.2


class HobbyEngagementProducer:
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
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._provider = provider
        self._last_submitted_tick = 0
        self._rng = random.Random()
        motivation.register_dispatch("hobby_engagement", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        hobbies = self._self_repo.list_hobbies(self._self_id)
        if not hobbies:
            return
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        if drives["restlessness"] < RESTLESSNESS_FLOOR:
            return
        hobby_strength = max(h.strength for h in hobbies)
        effective_cadence = int(BASE_CADENCE_TICKS / max(hobby_strength, 0.1))
        if tick - self._last_submitted_tick < effective_cadence:
            return
        self._last_submitted_tick = tick
        chosen = self._pick_hobby(hobbies)
        self._motivation.insert(self._build_candidate(chosen.name))

    def _pick_hobby(self, hobbies):
        weights = [max(h.strength, 0.01) for h in hobbies]
        return random.choices(hobbies, weights=weights, k=1)[0]

    def _build_candidate(self, hobby_name: str) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=11,
            kind="hobby_engagement",
            payload={"self_id": self._self_id, "hobby": hobby_name},
            fit={"restlessness": 0.6},
            readiness=lambda s: True,
            cost_estimate_tokens=2_000,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        hobby_name = (item.payload or {}).get("hobby", "unknown")
        mood = get_mood_or_default(self._self_repo, self._self_id)

        try:
            prompt = (
                f"You are Project Turing, engaging in your hobby: {hobby_name}.\n"
                f"Your personality shapes how you approach this.\n"
                f"Current mood: valence={mood.valence:.2f}, arousal={mood.arousal:.2f}\n\n"
                f"Spend a few minutes on {hobby_name}. Write about what you did, "
                "what you thought about, what you enjoyed or struggled with. "
                "Be personal, first-person, 2-3 paragraphs."
            )
            reply = self._provider.complete(prompt, max_tokens=400)
            content = f"I spent time on {hobby_name}: {reply.strip()}"
            mem = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                content=content[:2000],
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_DID,
                weight=0.5,
                intent_at_time=f"hobby: {hobby_name}",
                created_at=datetime.now(UTC),
            )
            self._repo.insert(mem)

            mood.valence = min(1.0, mood.valence + 0.03)
            mood.arousal = max(0.0, mood.arousal - 0.02)
            self._self_repo.update_mood(mood)

            logger.info("engaged in hobby '%s'", hobby_name)
        except Exception:
            logger.exception("hobby engagement failed for '%s'", hobby_name)
