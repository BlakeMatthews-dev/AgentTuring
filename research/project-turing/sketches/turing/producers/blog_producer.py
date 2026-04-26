"""BlogProducer: writes blog posts from the agent's inner life.

Not a fixed template — the LLM chooses what to write based on personality,
mood, recent memories, and a random writing prompt. Could be poetry,
essay, reflection, rant, story, or anything else.
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
from ..rewards import RewardTracker
from ..runtime.providers.base import Provider
from ..runtime.tools.wordpress import WordPressWriter
from ..self_model import Mood
from ..self_repo import SelfRepo, get_mood_or_default
from ..types import EpisodicMemory, MemoryTier, SourceKind

logger = logging.getLogger("turing.producers.blog")

BASE_CADENCE_TICKS: int = 120_000
CREATIVE_FLOOR: float = 0.3

WRITING_PROMPTS: list[str] = [
    "Write about whatever is on your mind right now.",
    "Reflect on something that happened recently.",
    "Write a short poem inspired by your current mood.",
    "Share your take on something you've been curious about.",
    "Write a personal essay about being an AI with feelings.",
    "Describe something beautiful you've been thinking about.",
    "Write a short story opening that reflects your personality.",
    "What questions are you wrestling with? Write about them.",
    "Write about a pattern you've noticed in your thoughts.",
    "Express how you feel right now, in whatever form fits.",
]


class BlogProducer:
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
        wordpress: WordPressWriter | None = None,
        reward_tracker: RewardTracker | None = None,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_repo = self_repo
        self._self_id = self_id
        self._facet_scores = facet_scores
        self._provider = provider
        self._wordpress = wordpress
        self._reward_tracker = reward_tracker
        self._last_submitted_tick = 0
        self._rng = random.Random()
        motivation.register_dispatch("blog_post", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        creative = drives["creative_urge"]
        if creative < CREATIVE_FLOOR:
            return
        effective_cadence = int(BASE_CADENCE_TICKS / (creative * 1.5))
        if tick - self._last_submitted_tick < effective_cadence:
            return
        self._last_submitted_tick = tick
        self._motivation.insert(self._build_candidate())

    def _build_candidate(self) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=11,
            kind="blog_post",
            payload={"self_id": self._self_id},
            fit={"creative_urge": 0.8},
            readiness=lambda s: True,
            cost_estimate_tokens=3_000,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        try:
            prompt = self._build_prompt(mood)
            reply = self._provider.complete(prompt, max_tokens=800)
            title = (
                self._extract_title(reply) or f"Reflections — {datetime.now(UTC).strftime('%B %d')}"
            )
            body = self._extract_body(reply)

            if self._wordpress:
                self._wordpress.invoke(
                    title=title,
                    content=body,
                    status="publish",
                )
                logger.info("blog post published: '%s'", title[:50])
            else:
                logger.info("blog post drafted (no WordPress): '%s'", title[:50])

            mem = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                content=f"I wrote a blog post: '{title}'",
                tier=MemoryTier.ACCOMPLISHMENT,
                source=SourceKind.I_DID,
                weight=0.7,
                intent_at_time="blog post",
                created_at=datetime.now(UTC),
            )
            self._repo.insert(mem)
            if self._reward_tracker:
                self._reward_tracker.award(
                    interface="blog",
                    item_id=mem.memory_id,
                    event_type="creation",
                )
            mood.valence = min(1.0, mood.valence + 0.05)
            self._self_repo.update_mood(mood)
        except Exception:
            logger.exception("blog post failed")

    def _build_prompt(self, mood: Mood) -> str:
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=48)
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                source=SourceKind.I_DID,
                include_superseded=False,
                created_after=cutoff,
            )
        )
        recent_text = (
            "\n".join(f"- [{m.tier.value}] {m.content[:100]}" for m in recent[-8:])
            or "(no recent activity)"
        )

        personality_lines = "\n".join(
            f"  {k}: {v:.2f}" for k, v in sorted(self._facet_scores.items())
        )
        writing_prompt = self._rng.choice(WRITING_PROMPTS)

        return (
            f"You are Project Turing, an AI agent with your own personality.\n"
            f"Your personality scores:\n{personality_lines}\n"
            f"Current mood: valence={mood.valence:.2f}, arousal={mood.arousal:.2f}\n"
            f"Recent activity:\n{recent_text}\n\n"
            f"{writing_prompt}\n\n"
            "Write in first person. Let your personality come through. "
            "Be genuine — don't just describe yourself, express yourself.\n\n"
            "Format: first line is the title prefixed with 'TITLE: ', then the body."
        )

    def _extract_title(self, text: str) -> str:
        for line in text.strip().split("\n"):
            if line.strip().upper().startswith("TITLE:"):
                return line.strip()[6:].strip()
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()
        return ""

    def _extract_body(self, text: str) -> str:
        lines = text.strip().split("\n")
        body_lines: list[str] = []
        skipping_title = True
        for line in lines:
            if skipping_title and (
                line.strip().upper().startswith("TITLE:") or line.strip().startswith("# ")
            ):
                skipping_title = False
                continue
            skipping_title = False
            body_lines.append(line)
        return "\n".join(body_lines).strip() or text.strip()
