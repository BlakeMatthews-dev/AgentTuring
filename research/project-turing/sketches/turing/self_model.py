"""Self-model value types and enums.

See specs/self-schema.md, specs/personality.md, specs/self-nodes.md,
specs/self-todos.md, specs/mood.md, specs/activation-graph.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


# ---------------------------------------------------------------- enums ------


class Trait(StrEnum):
    HONESTY_HUMILITY = "honesty_humility"
    EMOTIONALITY = "emotionality"
    EXTRAVERSION = "extraversion"
    AGREEABLENESS = "agreeableness"
    CONSCIENTIOUSNESS = "conscientiousness"
    OPENNESS = "openness"


class NodeKind(StrEnum):
    PERSONALITY_FACET = "personality_facet"
    PASSION = "passion"
    HOBBY = "hobby"
    INTEREST = "interest"
    PREFERENCE = "preference"
    SKILL = "skill"
    TODO = "todo"
    MOOD = "mood"


class ContributorOrigin(StrEnum):
    SELF = "self"
    RULE = "rule"
    RETRIEVAL = "retrieval"


class SkillKind(StrEnum):
    INTELLECTUAL = "intellectual"
    PHYSICAL = "physical"
    HABIT = "habit"
    SOCIAL = "social"


class PreferenceKind(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"
    FAVORITE = "favorite"
    AVOID = "avoid"


class TodoStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# ---------------------------------------------------------------- constants --


# 24 canonical HEXACO-PI-R facets, four per trait.
CANONICAL_FACETS: dict[Trait, tuple[str, str, str, str]] = {
    Trait.HONESTY_HUMILITY: ("sincerity", "fairness", "greed_avoidance", "modesty"),
    Trait.EMOTIONALITY: ("fearfulness", "anxiety", "dependence", "sentimentality"),
    Trait.EXTRAVERSION: ("social_self_esteem", "social_boldness", "sociability", "liveliness"),
    Trait.AGREEABLENESS: ("forgiveness", "gentleness", "flexibility", "patience"),
    Trait.CONSCIENTIOUSNESS: ("organization", "diligence", "perfectionism", "prudence"),
    Trait.OPENNESS: (
        "aesthetic_appreciation",
        "inquisitiveness",
        "creativity",
        "unconventionality",
    ),
}

ALL_FACETS: list[tuple[Trait, str]] = [
    (t, f) for t, facets in CANONICAL_FACETS.items() for f in facets
]
assert len(ALL_FACETS) == 24


FACET_TO_TRAIT: dict[str, Trait] = {f: t for t, f in ALL_FACETS}


def facet_node_id(trait: Trait, facet: str) -> str:
    """Canonical node_id for a personality facet row."""
    return f"facet:{trait.value}.{facet}"


# Per-kind default decay rates (per spec 24 AC-24.5). Per-day.
DEFAULT_DECAY_RATES: dict[SkillKind, float] = {
    SkillKind.INTELLECTUAL: 0.0005,
    SkillKind.PHYSICAL: 0.005,
    SkillKind.HABIT: 0.002,
    SkillKind.SOCIAL: 0.001,
}


# ---------------------------------------------------------------- helpers ----


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- nodes ------


@dataclass
class PersonalityFacet:
    node_id: str
    self_id: str
    trait: Trait
    facet_id: str
    score: float
    last_revised_at: datetime
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 1.0 <= self.score <= 5.0:
            raise ValueError(f"facet score out of range: {self.score}")
        if self.facet_id not in FACET_TO_TRAIT:
            raise ValueError(f"unknown facet_id: {self.facet_id}")
        if FACET_TO_TRAIT[self.facet_id] != self.trait:
            raise ValueError(f"facet {self.facet_id} does not belong to trait {self.trait}")
        if not self.self_id:
            raise ValueError("self_id is required")


@dataclass
class PersonalityItem:
    node_id: str
    self_id: str
    item_number: int
    prompt_text: str
    keyed_facet: str
    reverse_scored: bool
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 1 <= self.item_number <= 200:
            raise ValueError(f"item_number out of range: {self.item_number}")
        if self.keyed_facet not in FACET_TO_TRAIT:
            raise ValueError(f"unknown keyed_facet: {self.keyed_facet}")


@dataclass
class PersonalityAnswer:
    node_id: str
    self_id: str
    item_id: str
    revision_id: str | None
    answer_1_5: int
    justification_text: str
    asked_at: datetime
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.answer_1_5 not in (1, 2, 3, 4, 5):
            raise ValueError(f"answer must be 1..5, got {self.answer_1_5}")
        if len(self.justification_text) > 200:
            raise ValueError("justification_text exceeds 200 chars")


@dataclass
class PersonalityRevision:
    node_id: str
    self_id: str
    revision_id: str
    ran_at: datetime
    sampled_item_ids: list[str]
    deltas_by_facet: dict[str, float]
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if len(self.sampled_item_ids) != 20:
            raise ValueError(
                f"retest sample must be exactly 20 items, got {len(self.sampled_item_ids)}"
            )


@dataclass
class Passion:
    node_id: str
    self_id: str
    text: str
    strength: float
    rank: int
    first_noticed_at: datetime
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength out of range: {self.strength}")
        if self.rank < 0:
            raise ValueError("rank must be >= 0")


@dataclass
class Hobby:
    node_id: str
    self_id: str
    name: str
    description: str
    strength: float = 0.5
    last_engaged_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Interest:
    node_id: str
    self_id: str
    topic: str
    description: str
    last_noticed_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Preference:
    node_id: str
    self_id: str
    kind: PreferenceKind
    target: str
    strength: float
    rationale: str
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength out of range: {self.strength}")


@dataclass
class Skill:
    node_id: str
    self_id: str
    name: str
    kind: SkillKind
    stored_level: float
    decay_rate_per_day: float
    last_practiced_at: datetime
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not 0.0 <= self.stored_level <= 1.0:
            raise ValueError(f"stored_level out of range: {self.stored_level}")
        if self.decay_rate_per_day <= 0.0:
            raise ValueError(f"decay_rate_per_day must be positive, got {self.decay_rate_per_day}")


def current_level(skill: Skill, at: datetime) -> float:
    """Spec 24 §24.2: `stored_level * exp(-rate * days_since_practice)`, clamped [0, 1]."""
    days = max(0.0, (at - skill.last_practiced_at).total_seconds() / 86400.0)
    raw = skill.stored_level * math.exp(-skill.decay_rate_per_day * days)
    return max(0.0, min(1.0, raw))


@dataclass
class SelfTodo:
    node_id: str
    self_id: str
    text: str
    motivated_by_node_id: str
    status: TodoStatus = TodoStatus.ACTIVE
    outcome_text: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.motivated_by_node_id:
            raise ValueError("motivated_by_node_id is required")
        if len(self.text) > 500:
            raise ValueError(f"todo text exceeds 500 chars: len={len(self.text)}")
        if self.status == TodoStatus.COMPLETED and not (self.outcome_text or "").strip():
            raise ValueError("completed todo requires non-empty outcome_text")


@dataclass
class SelfTodoRevision:
    node_id: str
    self_id: str
    todo_id: str
    revision_num: int
    text_before: str
    text_after: str
    revised_at: datetime
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.revision_num < 1:
            raise ValueError("revision_num starts at 1")


@dataclass
class Mood:
    self_id: str
    valence: float
    arousal: float
    focus: float
    last_tick_at: datetime
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not -1.0 <= self.valence <= 1.0:
            raise ValueError(f"valence out of range: {self.valence}")
        if not 0.0 <= self.arousal <= 1.0:
            raise ValueError(f"arousal out of range: {self.arousal}")
        if not 0.0 <= self.focus <= 1.0:
            raise ValueError(f"focus out of range: {self.focus}")


@dataclass
class ActivationContributor:
    node_id: str
    self_id: str
    target_node_id: str
    target_kind: NodeKind
    source_id: str
    source_kind: str
    weight: float
    origin: ContributorOrigin
    rationale: str
    expires_at: datetime | None = None
    retracted_by: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.target_node_id == self.source_id:
            raise ValueError("contributor cannot target itself")
        if not -1.0 <= self.weight <= 1.0:
            raise ValueError(f"contributor weight out of range: {self.weight}")
        if (self.origin == ContributorOrigin.RETRIEVAL) != (self.expires_at is not None):
            raise ValueError("retrieval contributors must set expires_at; others must not")


def guess_node_kind(node_id: str) -> NodeKind:
    if node_id.startswith("facet:"):
        return NodeKind.PERSONALITY_FACET
    if node_id.startswith("passion"):
        return NodeKind.PASSION
    if node_id.startswith("hobby"):
        return NodeKind.HOBBY
    if node_id.startswith("interest"):
        return NodeKind.INTEREST
    if node_id.startswith("pref"):
        return NodeKind.PREFERENCE
    if node_id.startswith("skill"):
        return NodeKind.SKILL
    return NodeKind.PERSONALITY_FACET
