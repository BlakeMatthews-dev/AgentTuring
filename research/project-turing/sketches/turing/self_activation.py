"""Activation graph: contributor aggregation and `active_now` computation.

See specs/activation-graph.md.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .self_mood import mood_descriptor  # noqa: F401  (re-exported convenience)
from .self_model import current_level
from .self_repo import SelfRepo

if TYPE_CHECKING:
    from .repo import Repo as MemoryRepo


SCALE: float = 2.0
RETRIEVAL_TTL: timedelta = timedelta(minutes=5)
RETRIEVAL_WEIGHT_COEFFICIENT: float = 0.4
HOBBY_RECENCY_DAYS: float = 14.0
INTEREST_RECENCY_DAYS: float = 30.0


@dataclass
class ActivationContext:
    self_id: str
    now: datetime
    retrieval_similarity: dict[str, float] = field(default_factory=dict)
    memory_repo: MemoryRepo | None = None

    @property
    def hash(self) -> str:
        return f"{self_id_or_none(self.self_id)}|{self.now.isoformat()}"


def self_id_or_none(s: str | None) -> str:
    return s or ""


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _recency_state(last: datetime | None, now: datetime, window_days: float) -> float:
    if last is None:
        return 0.0
    days = (now - last).total_seconds() / 86400.0
    if days <= 0:
        return 1.0
    if days >= window_days:
        return 0.0
    return 1.0 - (days / window_days)


def source_state(repo: SelfRepo, source_id: str, source_kind: str, ctx: ActivationContext) -> float:
    """Resolve a source's current state to `[0.0, 1.0]`."""
    if source_kind == "personality_facet":
        facet = repo.get_facet(source_id)
        return max(0.0, min(1.0, (facet.score - 1.0) / 4.0))
    if source_kind == "passion":
        p = repo.get_passion(source_id)
        return p.strength
    if source_kind == "preference":
        for p in repo.list_preferences(ctx.self_id):
            if p.node_id == source_id:
                return p.strength
        raise KeyError(source_id)
    if source_kind == "hobby":
        for h in repo.list_hobbies(ctx.self_id):
            if h.node_id == source_id:
                return _recency_state(h.last_engaged_at, ctx.now, HOBBY_RECENCY_DAYS)
        raise KeyError(source_id)
    if source_kind == "interest":
        for i in repo.list_interests(ctx.self_id):
            if i.node_id == source_id:
                return _recency_state(i.last_noticed_at, ctx.now, INTEREST_RECENCY_DAYS)
        raise KeyError(source_id)
    if source_kind == "skill":
        s = repo.get_skill(source_id)
        return current_level(s, ctx.now)
    if source_kind == "mood":
        m = repo.get_mood(ctx.self_id)
        return (m.valence + 1.0) / 2.0
    if source_kind == "memory":
        if ctx.memory_repo is not None:
            mem = ctx.memory_repo.get(source_id)
            if mem is None or mem.deleted:
                raise KeyError(source_id)
            return max(0.0, min(1.0, mem.weight))
        warnings.warn(
            "ActivationContext.memory_repo is None; using legacy 0.5 for memory source_state",
            DeprecationWarning,
            stacklevel=2,
        )
        return 0.5
    if source_kind == "rule":
        return 1.0
    if source_kind == "retrieval":
        return ctx.retrieval_similarity.get(source_id, 0.0)
    raise ValueError(f"unknown source_kind: {source_kind}")


def active_now(repo: SelfRepo, node_id: str, ctx: ActivationContext) -> float:
    """Bounded activation: sigmoid(Σ weight × source_state / SCALE), [0, 1]."""
    contribs = repo.active_contributors_for(node_id, at=ctx.now)
    if not contribs:
        # Spec 25 AC-25.20: zero durable contributors → 0.5 neutral baseline.
        return 0.5
    raw = 0.0
    for c in contribs:
        try:
            s = source_state(repo, c.source_id, c.source_kind, ctx)
        except KeyError:
            # Spec 25 AC-25.23: dangling source → weight-0 for this compute.
            continue
        raw += c.weight * s
    return max(0.0, min(1.0, _sigmoid(raw / SCALE)))
