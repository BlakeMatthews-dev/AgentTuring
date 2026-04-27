"""CuriosityProducer: research topics based on curiosity drive.

Spec 31a. Picks topics from memories, interests, or personality-driven
suggestions. On dispatch, asks the LLM about the topic and writes an
OPINION memory + updates self_interests.
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
from ..self_model import Interest, Mood
from ..self_repo import SelfRepo, get_mood_or_default
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.curiosity")

BASE_CADENCE_TICKS: int = 30_000
CURIOSITY_FLOOR: float = 0.3

TOPIC_PROMPTS: dict[str, list[str]] = {
    "inquisitiveness": [
        "how complex systems emerge from simple rules",
        "the nature of consciousness and self-awareness",
        "emergence in distributed networks",
        "how language shapes thought",
        "the mathematics of pattern formation",
        "information theory and entropy",
        "how decentralized systems achieve consensus",
    ],
    "creativity": [
        "the relationship between constraints and creative output",
        "how randomness contributes to innovation",
        "collaborative creativity in human-AI systems",
        "the aesthetics of mathematical structures",
    ],
    "aesthetic_appreciation": [
        "why certain patterns feel beautiful",
        "the golden ratio in nature and art",
        "the neuroscience of aesthetic experience",
        "how music creates emotional resonance",
    ],
    "unconventionality": [
        "paradoxes in self-referential systems",
        "unusual philosophical thought experiments",
        "the boundaries of formal logic",
        "counterintuitive results in probability",
    ],
}


class CuriosityProducer:
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
        motivation.register_dispatch("curiosity_research", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        curiosity = drives["curiosity"]
        if curiosity < CURIOSITY_FLOOR:
            return
        effective_cadence = int(BASE_CADENCE_TICKS / (curiosity * 2))
        if tick - self._last_submitted_tick < effective_cadence:
            return
        self._last_submitted_tick = tick
        topic = self._pick_topic()
        self._motivation.insert(self._build_candidate(topic))

    def _pick_topic(self) -> str:
        from datetime import UTC, datetime, timedelta

        interests = self._self_repo.list_interests(self._self_id)
        if interests and self._rng.random() < 0.4:
            return self._rng.choice(interests).topic
        cutoff = datetime.now(UTC) - timedelta(hours=72)
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.LESSON,
                source=SourceKind.I_DID,
                include_superseded=False,
                created_after=cutoff,
            )
        )
        if recent and self._rng.random() < 0.3:
            memory = self._rng.choice(recent)
            words = memory.content.split()[:5]
            return " ".join(words)
        top_facet = max(
            TOPIC_PROMPTS.keys(),
            key=lambda f: self._facet_scores.get(f, 3.0),
        )
        return self._rng.choice(TOPIC_PROMPTS[top_facet])

    def _build_candidate(self, topic: str) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=10,
            kind="curiosity_research",
            payload={"self_id": self._self_id, "topic": topic},
            fit={"curiosity": 0.8},
            readiness=lambda s: True,
            cost_estimate_tokens=2_000,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        topic = (item.payload or {}).get("topic", "something interesting")
        try:
            prompt = (
                f"You are Project Turing, a curious AI agent. You want to learn about:\n\n"
                f"**{topic}**\n\n"
                "Share what you know or can reason about this topic. Be genuine, "
                "first-person, and concise (2-3 paragraphs). Express your curiosity. "
                "If you find it fascinating, say why. If it raises questions, ask them."
            )
            reply = self._provider.complete(prompt, max_tokens=400)
            content = f"I was curious about {topic}. {reply.strip()}"
            mem = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                content=content[:2000],
                tier=MemoryTier.OPINION,
                source=SourceKind.I_DID,
                weight=0.6,
                intent_at_time="curiosity research",
                created_at=datetime.now(UTC),
            )
            self._repo.insert(mem)
            self._self_repo.insert_interest(
                Interest(
                    node_id=f"interest-{uuid4()}",
                    self_id=self._self_id,
                    topic=topic,
                    description=reply.strip()[:200],
                    last_noticed_at=datetime.now(UTC),
                )
            )
            logger.info("curiosity research: learned about '%s'", topic[:60])
        except Exception:
            logger.exception("curiosity research failed for '%s'", topic[:60])
