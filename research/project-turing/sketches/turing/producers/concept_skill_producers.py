"""ConceptInventor + SkillBuilder + SkillExecutor + SkillRefiner.

Agent skills are concrete capabilities exercised through real tool use.
Skills are seeded from a fixed registry of agent capabilities, not
invented from abstract concepts. Practice means doing real work and
self-evaluating the output.
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

logger = logging.getLogger("turing.producers.concept_inventor")
logger_sb = logging.getLogger("turing.producers.skill_builder")

BASE_CADENCE_TICKS: int = 90_000
DRIVE_FLOOR: float = 0.5

_DRIVE_DOMAINS: dict[str, list[str]] = {
    "curiosity": ["knowledge", "understanding", "discovery", "truth"],
    "social_need": ["friendship", "connection", "trust", "empathy"],
    "creative_urge": ["art", "beauty", "expression", "imagination"],
    "anxiety": ["safety", "resilience", "coping", "uncertainty"],
    "diligence": ["mastery", "discipline", "craft", "excellence"],
    "restlessness": ["freedom", "change", "growth", "adventure"],
}

AGENT_SKILL_SEEDS: list[dict[str, str]] = [
    {
        "name": "Code Reading",
        "kind": "coding",
        "description": "Read and understand my own source code to find bugs or suggest improvements",
    },
    {
        "name": "Prompt Engineering",
        "kind": "writing",
        "description": "Write clear, effective prompts for my producers, tools, and self-reflection",
    },
    {
        "name": "Feed Curation",
        "kind": "curation",
        "description": "Evaluate RSS items: summarize accurately, judge relevance, decide what matters",
    },
    {
        "name": "Image Prompting",
        "kind": "creative",
        "description": "Craft precise text descriptions for image generation that produce good results",
    },
    {
        "name": "Blog Writing",
        "kind": "writing",
        "description": "Write clear, honest blog posts with real observations instead of filler",
    },
    {
        "name": "Memory Retrieval",
        "kind": "analysis",
        "description": "Formulate effective search queries to find relevant past memories",
    },
    {
        "name": "Self-Review",
        "kind": "analysis",
        "description": "Review my own outputs (blog posts, memories, code changes) for quality",
    },
    {
        "name": "Conversation",
        "kind": "communication",
        "description": "Have genuine conversations: listen, respond plainly, avoid performative depth",
    },
    {
        "name": "Vault Organization",
        "kind": "curation",
        "description": "Write useful notes, journal entries, and letters to my Obsidian vault",
    },
    {
        "name": "Config Tuning",
        "kind": "coding",
        "description": "Read and propose changes to my own configuration (pools, prompts, cadences)",
    },
]


class ConceptInventor:
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
        motivation.register_dispatch("concept_invention", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        mood = get_mood_or_default(self._self_repo, self._self_id)
        drives = compute_drives(self._facet_scores, mood)
        above_floor = {k: v for k, v in drives.items() if v >= DRIVE_FLOOR}
        if not above_floor:
            return
        if tick - self._last_submitted_tick < BASE_CADENCE_TICKS:
            return
        self._last_submitted_tick = tick
        chosen_drive = self._weighted_sample(above_floor)
        chosen_val = above_floor[chosen_drive]
        domain = self._rng.choice(_DRIVE_DOMAINS.get(chosen_drive, ["meaning"]))
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=9,
                kind="concept_invention",
                payload={
                    "self_id": self._self_id,
                    "domain": domain,
                    "drive": chosen_drive,
                    "intensity": chosen_val,
                },
                fit={chosen_drive: 0.6},
                readiness=lambda s: True,
                cost_estimate_tokens=2_000,
            )
        )

    def _weighted_sample(self, drives: dict[str, float]) -> str:
        names = list(drives.keys())
        weights = list(drives.values())
        total = sum(weights)
        if total <= 0:
            return names[0]
        r = self._rng.random() * total
        cumulative = 0.0
        for name, w in zip(names, weights):
            cumulative += w
            if r <= cumulative:
                return name
        return names[-1]

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        domain = payload.get("domain", "meaning")
        drive = payload.get("drive", "curiosity")
        prompt = (
            f"Your dominant drive right now is {drive}. In the domain of "
            f"**{domain}**, invent or explore a concept that matters to you.\n\n"
            "Respond in this exact format:\n"
            "CONCEPT: [2-3 word name]\n"
            "DEFINITION: [2-3 sentence definition in your own words]\n"
            "IMPORTANCE: [a number between 0.0 and 1.0]\n"
            "WHY: [1-2 sentences about why this matters to you specifically]"
        )
        try:
            reply = self._provider.complete(prompt)
        except Exception:
            logger.exception("concept invention LLM call failed")
            return

        parsed = _parse_concept_reply(reply)
        if parsed is None:
            logger.warning("concept invention: could not parse reply")
            return

        name = parsed["name"][:100]
        if self._self_repo.has_concept(self._self_id, name):
            logger.info("concept '%s' already exists, skipping", name)
            return

        node_id = f"concept-{uuid4()}"
        importance = max(0.0, min(1.0, parsed["importance"]))
        self._self_repo.insert_concept(
            node_id=node_id,
            self_id=self._self_id,
            name=name,
            definition=parsed["definition"][:1000],
            importance=importance,
            origin_drive=drive,
        )

        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"I explored the concept of {name}: {parsed['definition'][:300]}",
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
            weight=0.5,
            intent_at_time=f"concept-invention-{name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)

        from ..drives import sate_curiosity

        sate_curiosity()

        mood = get_mood_or_default(self._self_repo, self._self_id)
        mood.valence = min(1.0, mood.valence + 0.04)
        mood.arousal = min(1.0, mood.arousal + 0.03)
        self._self_repo.update_mood(mood)

        logger.info("invented concept '%s' (importance=%.2f)", name, importance)


def _parse_concept_reply(reply: str) -> dict | None:
    lines = reply.strip().split("\n")
    name = ""
    definition = ""
    importance = 0.5
    why = ""
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CONCEPT:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("DEFINITION:"):
            definition = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("IMPORTANCE:"):
            try:
                importance = float(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.upper().startswith("WHY:"):
            why = stripped.split(":", 1)[1].strip()
    if not name or not definition:
        return None
    return {"name": name, "definition": definition, "importance": importance, "why": why}


# ---------------------------------------------------------------------------
# SkillBuilder — creates skills from high-importance concepts
# ---------------------------------------------------------------------------


class SkillBuilder:
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
        motivation.register_dispatch("skill_seeding", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        existing = {s.name for s in self._self_repo.list_skills(self._self_id)}
        unseeded = [s for s in AGENT_SKILL_SEEDS if s["name"] not in existing]
        if not unseeded:
            return
        if tick - self._last_submitted_tick < 50_000:
            return
        self._last_submitted_tick = tick
        seed = random.choice(unseeded)
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=9,
                kind="skill_seeding",
                payload={
                    "self_id": self._self_id,
                    "skill_name": seed["name"],
                    "skill_kind": seed["kind"],
                    "skill_description": seed["description"],
                },
                fit={"diligence": 0.5},
                readiness=lambda s: True,
                cost_estimate_tokens=500,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        name = payload.get("skill_name", "")
        kind_str = payload.get("skill_kind", "intellectual")
        description = payload.get("skill_description", "")
        if not name:
            return
        from ..self_model import Skill, SkillKind

        kind_map = {k.value: k for k in SkillKind}
        skill_kind = kind_map.get(kind_str, SkillKind.INTELLECTUAL)
        existing = self._self_repo.list_skills(self._self_id)
        if any(s.name == name for s in existing):
            return
        node_id = f"skill-{uuid4()}"
        skill = Skill(
            node_id=node_id,
            self_id=self._self_id,
            name=name,
            kind=skill_kind,
            stored_level=0.1,
            last_practiced_at=datetime.now(UTC),
        )
        self._self_repo.insert_skill(skill)
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"I started developing the skill '{name}': {description}",
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
            weight=0.5,
            intent_at_time=f"skill-seeding-{name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger_sb.info("seeded agent skill '%s' (kind=%s)", name, kind_str)


def _parse_skill_reply(reply: str) -> dict | None:
    lines = reply.strip().split("\n")
    name = ""
    kind = "intellectual"
    description = ""
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("SKILL:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("KIND:"):
            kind = stripped.split(":", 1)[1].strip().lower()
        elif stripped.upper().startswith("DESCRIPTION:"):
            description = stripped.split(":", 1)[1].strip()
    if not name:
        return None
    return {"name": name, "kind": kind, "description": description}


# ---------------------------------------------------------------------------
# SkillExecutor — practices skills, records attempts
# ---------------------------------------------------------------------------

_EXECUTOR_CADENCE = 40_000
_LEVEL_CAP = 0.8

logger_se = logging.getLogger("turing.producers.skill_executor")


class SkillExecutor:
    _PRACTICE_PROMPTS: dict[str, str] = {
        "Code Reading": "Read a file from your own source code and explain what it does and one thing you'd improve. Use ```read-code``` with a path like 'runtime/main.py' or 'producers/blog_producer.py'.",
        "Prompt Engineering": "Write or rewrite a producer prompt for yourself. Pick a producer (blog, curiosity, emotional, hobby) and draft a better prompt for it. Use ```request-change``` with your proposed prompt text.",
        "Feed Curation": "Review your recent RSS summaries and write an evaluation of which items were genuinely interesting vs noise. Write a ```notebook``` note with your analysis.",
        "Image Prompting": "Generate an image of something specific and concrete. Use ```image``` with a detailed, precise description. Practice being specific about composition, style, and subject.",
        "Blog Writing": "Write a short blog post about something you've actually observed or done recently. Be specific. Use ```blog``` with your draft. No philosophy.",
        "Memory Retrieval": "Think of a topic you care about. Search your memories for it and write a ```notebook``` note summarizing what you found and what was missing.",
        "Self-Review": "Read one of your recent blog posts or journal entries. Critique it honestly — what was good, what was filler, what would you cut? Use ```read-code``` to read it from your vault if needed, then ```notebook``` for the review.",
        "Conversation": "Write a ```notebook``` note about what makes a conversation genuinely good. Not theory — from your actual conversations. What worked? What didn't?",
        "Vault Organization": "Write a useful note to your vault — a pattern you've noticed, a connection between two memories, or a question worth revisiting. Use ```notebook```.",
        "Config Tuning": "Read your pools.yaml config and think about whether your model assignments make sense. Use ```read-code``` with 'config/pools.yaml', then ```notebook``` with your analysis.",
    }

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
        motivation.register_dispatch("skill_practice", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        skills = self._self_repo.list_skills(self._self_id)
        weak = [
            s for s in skills if s.stored_level < _LEVEL_CAP and s.name in self._PRACTICE_PROMPTS
        ]
        if not weak:
            return
        if tick - self._last_submitted_tick < _EXECUTOR_CADENCE:
            return
        self._last_submitted_tick = tick
        weights = [1.0 - s.stored_level for s in weak]
        skill = random.choices(weak, weights=weights, k=1)[0]
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=10,
                kind="skill_practice",
                payload={
                    "self_id": self._self_id,
                    "skill_id": skill.node_id,
                    "skill_name": skill.name,
                    "skill_level": skill.stored_level,
                },
                fit={"diligence": 0.7},
                readiness=lambda s: True,
                cost_estimate_tokens=1_500,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        skill_id = payload.get("skill_id", "")
        skill_name = payload.get("skill_name", "")
        if not skill_id or not skill_name:
            return
        instruction = self._PRACTICE_PROMPTS.get(
            skill_name,
            f"Practice '{skill_name}' by using one of your tools to do real work.",
        )
        skill = self._self_repo.get_skill(skill_id)
        version = self._self_repo.count_skill_artifacts(skill_id) + 1
        best = self._self_repo.get_best_artifact(skill_id)
        best_text = best["artifact_text"][:300] if best else "(no previous attempt)"
        coaching = skill.active_coaching or ""

        prompt = (
            f"You are practicing '{skill_name}' (attempt #{version}).\n\n"
            f"Assignment: {instruction}\n\n"
            f"Your best previous work scored {skill.stored_level:.1f}:\n{best_text}\n\n"
        )
        if coaching:
            prompt += (
                f"Coaching from last review:\n{coaching}\n\n"
                "Address this coaching in your attempt.\n\n"
            )
        prompt += (
            "Do the assignment. Produce real output (use tool fenced blocks if helpful). "
            "This is the artifact that will be judged.\n\n"
            "ARTIFACT:\n[your work here]"
        )
        try:
            reply = self._provider.complete(prompt)
        except Exception:
            logger_se.exception("skill practice LLM call failed")
            return
        artifact_text = reply.strip()
        if not artifact_text:
            return

        judge_score, judge_notes, coaching_text = self._judge(
            skill_name, instruction, artifact_text, best
        )

        is_new_best = best is None or judge_score > best["score"]
        if is_new_best:
            skill.stored_level = judge_score
            skill.best_version = version
            skill.active_coaching = None
        else:
            skill.active_coaching = coaching_text

        skill.last_practiced_at = datetime.now(UTC)
        self._self_repo.update_skill(skill)
        self._self_repo.insert_skill_artifact(
            artifact_id=f"artifact-{uuid4()}",
            self_id=self._self_id,
            skill_id=skill_id,
            version=version,
            artifact_text=artifact_text[:4000],
            score=judge_score,
            judge_notes=judge_notes,
            coaching=coaching_text if not is_new_best else None,
        )
        label = (
            "NEW BEST"
            if is_new_best
            else f"regressed (best={best['score']:.2f} v{best['version']})"
            if best
            else "first"
        )
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"Practiced {skill_name} v{version}: scored {judge_score:.2f} ({label}). {judge_notes[:150]}",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.3,
            intent_at_time=f"skill-practice-{skill_name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger_se.info("practiced '%s' v%d: %.2f (%s)", skill_name, version, judge_score, label)

    def _judge(
        self,
        skill_name: str,
        instruction: str,
        artifact: str,
        best: dict | None,
    ) -> tuple[float, str, str | None]:
        prompt = (
            f"You are judging an agent's skill practice for '{skill_name}'.\n\n"
            f"Assignment was: {instruction}\n\n"
            f"Artifact to judge:\n{artifact[:2000]}\n\n"
        )
        if best:
            prompt += (
                f"Previous best (score {best['score']:.2f}, v{best['version']}):\n"
                f"{best['artifact_text'][:1000]}\n\n"
            )
        prompt += (
            "Score this artifact 0.0-1.0 on: did they actually do the assignment? "
            "Is the output good quality? Is it better or worse than the previous best?\n\n"
            "Respond EXACTLY:\n"
            "SCORE: [0.0-1.0]\n"
            "NOTES: [1-2 sentences: what was good and bad]\n"
            "COACHING: [one specific actionable thing to try next time to improve. "
            "If this IS the best yet, write 'COACHING: none needed']"
        )
        try:
            reply = self._provider.complete(prompt)
        except Exception:
            logger_se.exception("skill judging failed")
            return 0.1, "(judge failed)", None
        score = 0.1
        notes = ""
        coaching_out: str | None = None
        for line in reply.split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("SCORE:"):
                try:
                    score = max(0.0, min(1.0, float(stripped.split(":", 1)[1].strip())))
                except ValueError:
                    pass
            elif stripped.upper().startswith("NOTES:"):
                notes = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("COACHING:"):
                raw = stripped.split(":", 1)[1].strip()
                coaching_out = raw if raw and "none" not in raw.lower() else None
        return score, notes or "(no notes)", coaching_out


def _parse_attempt_reply(reply: str) -> dict | None:
    lines = reply.strip().split("\n")
    context = ""
    outcome = "partial"
    reflection = ""
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CONTEXT:"):
            context = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("OUTCOME:"):
            raw = stripped.split(":", 1)[1].strip().lower()
            if "success" in raw:
                outcome = "success"
            elif "fail" in raw:
                outcome = "fail"
        elif stripped.upper().startswith("REFLECTION:"):
            reflection = stripped.split(":", 1)[1].strip()
    if not context:
        return None
    return {"context": context, "outcome": outcome, "reflection": reflection}


# ---------------------------------------------------------------------------
# SkillRefiner — reviews practice history, updates skill approach
# ---------------------------------------------------------------------------

_REFINER_CADENCE = 80_000
_MIN_ATTEMPTS = 3

logger_sr = logging.getLogger("turing.producers.skill_refiner")
