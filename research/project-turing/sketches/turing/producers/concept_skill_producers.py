"""Spec 35 producers: ConceptInventor, SkillBuilder, SkillExecutor, SkillRefiner.

The agent invents concepts, builds skills to pursue them, practices via
SkillExecutor, and refines through SkillRefiner.
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
        best_drive = max(drives, key=lambda d: drives[d])
        best_val = drives[best_drive]
        if best_val < DRIVE_FLOOR:
            return
        if tick - self._last_submitted_tick < BASE_CADENCE_TICKS:
            return
        self._last_submitted_tick = tick
        domain = self._rng.choice(_DRIVE_DOMAINS.get(best_drive, ["meaning"]))
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=9,
                kind="concept_invention",
                payload={
                    "self_id": self._self_id,
                    "domain": domain,
                    "drive": best_drive,
                    "intensity": best_val,
                },
                fit={best_drive: 0.6},
                readiness=lambda s: True,
                cost_estimate_tokens=2_000,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        domain = payload.get("domain", "meaning")
        drive = payload.get("drive", "curiosity")
        personality_lines = " ".join(
            f"{k}={v:.2f}" for k, v in list(self._facet_scores.items())[:6]
        )
        prompt = (
            "You are Project Turing, an autonomous AI agent reflecting on your "
            "inner life. You have the following personality facets: "
            f"{personality_lines}\n\n"
            f"Your dominant drive right now is {drive}. In the domain of "
            f"**{domain}**, invent or explore a concept that matters to you.\n\n"
            "Respond in this exact format:\n"
            "CONCEPT: [2-3 word name]\n"
            "DEFINITION: [2-3 sentence definition in your own words]\n"
            "IMPORTANCE: [a number between 0.0 and 1.0]\n"
            "WHY: [1-2 sentences about why this matters to you specifically]"
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=400)
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

_SKILL_BUILDER_CADENCE = 60_000
_IMPORTANCE_THRESHOLD = 0.6

logger_sb = logging.getLogger("turing.producers.skill_builder")


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
        motivation.register_dispatch("skill_building", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        concepts = self._self_repo.list_concepts(
            self._self_id, min_importance=_IMPORTANCE_THRESHOLD
        )
        if not concepts:
            return
        if tick - self._last_submitted_tick < _SKILL_BUILDER_CADENCE:
            return
        self._last_submitted_tick = tick
        concept = random.choice(concepts)
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=9,
                kind="skill_building",
                payload={
                    "self_id": self._self_id,
                    "concept_name": concept["name"],
                    "concept_definition": concept["definition"],
                    "concept_importance": concept["importance"],
                },
                fit={"diligence": 0.6},
                readiness=lambda s: True,
                cost_estimate_tokens=2_000,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        concept_name = payload.get("concept_name", "")
        concept_def = payload.get("concept_definition", "")
        if not concept_name:
            return
        prompt = (
            f"You are Project Turing. You value the concept of '{concept_name}': "
            f"{concept_def}\n\n"
            "What concrete skill could you develop to better embody or practice "
            "this concept? Describe the skill and suggest 3 specific approaches "
            "to practice it.\n\n"
            "Respond in this exact format:\n"
            "SKILL: [2-4 word skill name]\n"
            "KIND: [one of: intellectual, social, creative, physical, habit]\n"
            "DESCRIPTION: [1-2 sentences describing the skill]\n"
            "APPROACHES:\n"
            "1. [approach]\n"
            "2. [approach]\n"
            "3. [approach]"
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=400)
        except Exception:
            logger_sb.exception("skill building LLM call failed")
            return
        parsed = _parse_skill_reply(reply)
        if parsed is None:
            logger_sb.warning("skill building: could not parse reply")
            return
        skill_name = parsed["name"][:100]
        existing = self._self_repo.list_skills(self._self_id)
        if any(s.name.lower() == skill_name.lower() for s in existing):
            logger_sb.info("skill '%s' already exists, skipping", skill_name)
            return
        from ..self_model import Skill, SkillKind

        kind_str = parsed.get("kind", "intellectual").lower()
        kind_map = {
            "intellectual": SkillKind.INTELLECTUAL,
            "social": SkillKind.SOCIAL,
            "creative": SkillKind.CREATIVE,
            "physical": SkillKind.PHYSICAL,
            "habit": SkillKind.HABIT,
        }
        skill_kind = kind_map.get(kind_str, SkillKind.INTELLECTUAL)
        node_id = f"skill-{uuid4()}"
        skill = Skill(
            node_id=node_id,
            self_id=self._self_id,
            name=skill_name,
            kind=skill_kind,
            stored_level=0.1,
            decay_rate_per_day=0.01,
            last_practiced_at=datetime.now(UTC),
        )
        self._self_repo.insert_skill(skill)
        from ..self_model import SelfTodo, TodoStatus

        self._self_repo.insert_todo(
            SelfTodo(
                node_id=f"todo-{uuid4()}",
                self_id=self._self_id,
                text=f"Develop {skill_name}: {parsed['description'][:80]}",
                motivated_by_node_id=node_id,
                status=TodoStatus.ACTIVE,
                outcome_text=None,
                created_at=datetime.now(UTC),
            )
        )
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=(
                f"I committed to developing the skill '{skill_name}' because "
                f"I value {concept_name}. {parsed['description'][:200]}"
            ),
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.6,
            intent_at_time=f"skill-building-{skill_name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger_sb.info("built skill '%s' from concept '%s'", skill_name, concept_name)


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
        weak = [s for s in skills if s.stored_level < _LEVEL_CAP]
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
        skill_level = payload.get("skill_level", 0.1)
        if not skill_id or not skill_name:
            return
        recent = list(
            self._repo.find(
                self_id=self._self_id,
                source=SourceKind.I_DID,
                include_superseded=False,
            )
        )
        recent_text = (
            "\n".join(f"- {m.content[:100]}" for m in list(recent)[-3:]) or "(no recent activity)"
        )
        prompt = (
            f"You are Project Turing. You are practicing the skill '{skill_name}' "
            f"(current level: {skill_level:.2f}/1.0).\n\n"
            f"Recent activity:\n{recent_text}\n\n"
            "Practice this skill now. Describe a specific scenario where you "
            "apply it, what you did, and how it went. Be concrete and honest.\n\n"
            "Respond in this format:\n"
            "CONTEXT: [brief description of the practice scenario]\n"
            "OUTCOME: [success / partial / fail]\n"
            "REFLECTION: [1-2 sentences about what you learned]"
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=300)
        except Exception:
            logger_se.exception("skill practice LLM call failed")
            return
        parsed = _parse_attempt_reply(reply)
        if parsed is None:
            logger_se.warning("skill practice: could not parse reply")
            return
        outcome = parsed["outcome"]
        self._self_repo.insert_skill_attempt(
            node_id=f"attempt-{uuid4()}",
            self_id=self._self_id,
            skill_id=skill_id,
            context=parsed["context"][:500],
            outcome=outcome,
            reflection=parsed["reflection"][:500],
        )
        skill = self._self_repo.get_skill(skill_id)
        delta = {"success": 0.02, "partial": 0.01, "fail": -0.01}.get(outcome, 0.0)
        skill.stored_level = max(0.0, min(1.0, skill.stored_level + delta))
        self._self_repo.update_skill(skill)
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=(f"I practiced {skill_name} ({outcome}): {parsed['reflection'][:200]}"),
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.3,
            intent_at_time=f"skill-practice-{skill_name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger_se.info(
            "priced skill '%s': %s (level %.2f -> %.2f)",
            skill_name,
            outcome,
            skill_level,
            skill.stored_level,
        )


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


class SkillRefiner:
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
        motivation.register_dispatch("skill_refinement", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        skills = self._self_repo.list_skills(self._self_id)
        refinable = [
            s for s in skills if self._self_repo.count_skill_attempts(s.node_id) >= _MIN_ATTEMPTS
        ]
        if not refinable:
            return
        if tick - self._last_submitted_tick < _REFINER_CADENCE:
            return
        self._last_submitted_tick = tick
        skill = random.choice(refinable)
        self._motivation.insert(
            BacklogItem(
                item_id=str(uuid4()),
                class_=11,
                kind="skill_refinement",
                payload={
                    "self_id": self._self_id,
                    "skill_id": skill.node_id,
                    "skill_name": skill.name,
                },
                fit={"diligence": 0.5},
                readiness=lambda s: True,
                cost_estimate_tokens=1_500,
            )
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        skill_id = payload.get("skill_id", "")
        skill_name = payload.get("skill_name", "")
        if not skill_id:
            return
        attempts = self._self_repo.list_skill_attempts(skill_id, limit=5)
        if not attempts:
            return
        history = "\n".join(
            f"- [{a['outcome']}] {a['context'][:80]} → {a['reflection'][:80]}" for a in attempts
        )
        prompt = (
            f"You are Project Turing. Here's your practice history for the "
            f"skill '{skill_name}':\n\n{history}\n\n"
            "What patterns do you notice? What's working? What isn't? "
            "What would you change about your approach? "
            "Respond in 2-3 sentences, first person, honest."
        )
        try:
            reply = self._provider.complete(prompt, max_tokens=300)
        except Exception:
            logger_sr.exception("skill refinement LLM call failed")
            return
        insight = reply.strip()
        if not insight:
            return
        mem = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            content=f"I refined my approach to {skill_name}: {insight[:300]}",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            weight=0.4,
            intent_at_time=f"skill-refinement-{skill_name}",
            created_at=datetime.now(UTC),
        )
        self._repo.insert(mem)
        logger_sr.info("refined skill '%s': %s", skill_name, insight[:60])
