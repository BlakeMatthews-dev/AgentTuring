"""EpisodicMemory, SourceKind, MemoryTier. See specs/schema.md and specs/tiers.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MemoryTier(StrEnum):
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    LESSON = "lesson"
    REGRET = "regret"
    ACCOMPLISHMENT = "accomplishment"
    AFFIRMATION = "affirmation"
    WISDOM = "wisdom"


class SourceKind(StrEnum):
    I_DID = "i_did"
    I_WAS_TOLD = "i_was_told"
    I_IMAGINED = "i_imagined"


DURABLE_TIERS: frozenset[MemoryTier] = frozenset(
    {
        MemoryTier.REGRET,
        MemoryTier.ACCOMPLISHMENT,
        MemoryTier.AFFIRMATION,
        MemoryTier.WISDOM,
    }
)


# Fields that can be modified after construction. Per INV-6.
_MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "superseded_by",
        "last_accessed_at",
        "reinforcement_count",
        "contradiction_count",
        "deleted",
    }
)


@dataclass
class EpisodicMemory:
    """A single memory with first-person markers and lineage.

    Most fields are frozen after construction (INV-6). The few mutable fields
    are listed in `_MUTABLE_FIELDS`. `superseded_by` is settable only once
    (from None to a value).
    """

    memory_id: str
    self_id: str
    tier: MemoryTier
    content: str
    weight: float
    source: SourceKind
    affect: float = 0.0
    confidence_at_creation: float = 0.0
    surprise_delta: float = 0.0
    intent_at_time: str = ""
    supersedes: str | None = None
    superseded_by: str | None = None
    origin_episode_id: str | None = None
    immutable: bool = False
    reinforcement_count: int = 0
    contradiction_count: int = 0
    deleted: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.self_id:
            raise ValueError("self_id is required")
        if not -1.0 <= self.affect <= 1.0:
            raise ValueError(f"affect out of range: {self.affect}")
        if not 0.0 <= self.confidence_at_creation <= 1.0:
            raise ValueError(
                f"confidence_at_creation out of range: {self.confidence_at_creation}"
            )
        if not 0.0 <= self.surprise_delta <= 1.0:
            raise ValueError(f"surprise_delta out of range: {self.surprise_delta}")
        if self.supersedes is not None and self.supersedes == self.memory_id:
            raise ValueError("memory cannot supersede itself")
        if self.tier in DURABLE_TIERS and self.source != SourceKind.I_DID:
            raise ValueError(
                f"{self.tier.value} requires source=i_did; got {self.source.value}"
            )
        if self.tier == MemoryTier.ACCOMPLISHMENT and not self.intent_at_time:
            raise ValueError("ACCOMPLISHMENT requires non-empty intent_at_time")

    def __setattr__(self, name: str, value: Any) -> None:
        # During __init__, __dict__ is populated one field at a time; the
        # guard only trips if the field has already been set.
        already_set = name in self.__dict__
        if already_set and name not in _MUTABLE_FIELDS:
            raise AttributeError(f"{name!r} is frozen after construction")
        if (
            name == "superseded_by"
            and already_set
            and self.__dict__.get("superseded_by") is not None
        ):
            raise AttributeError("superseded_by is settable only once")
        super().__setattr__(name, value)
