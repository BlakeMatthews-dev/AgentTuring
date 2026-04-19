"""Write handlers for REGRET, ACCOMPLISHMENT, AFFIRMATION. See specs/write-paths.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from .repo import Repo, RepoError
from .tiers import WEIGHT_BOUNDS, clamp_weight
from .types import EpisodicMemory, MemoryTier, SourceKind


# Seed thresholds (runtime-tunable via tuning.md; these are defaults).
REGRET_SURPRISE_THRESHOLD: float = 0.4
REGRET_AFFECT_THRESHOLD: float = 0.3
ACCOMPLISHMENT_SURPRISE_THRESHOLD: float = 0.3
ACCOMPLISHMENT_AFFECT_THRESHOLD: float = 0.3


_STANCE_TIERS: frozenset[MemoryTier] = frozenset(
    {MemoryTier.HYPOTHESIS, MemoryTier.OPINION, MemoryTier.LESSON}
)


@dataclass(frozen=True)
class Outcome:
    affect: float
    surprise_delta: float
    confidence_at_creation: float = 0.0


def _new_id() -> str:
    return str(uuid4())


def handle_regret_candidate(
    repo: Repo,
    predecessor_id: str,
    outcome: Outcome,
    *,
    now: datetime | None = None,
    thresholds: tuple[float, float] = (
        REGRET_SURPRISE_THRESHOLD,
        REGRET_AFFECT_THRESHOLD,
    ),
) -> str | None:
    """Try to mint a REGRET superseding the given predecessor.

    Returns the new REGRET's memory_id if minted, or None if the outcome
    did not meet thresholds. Raises if the predecessor is not a valid
    stance-bearing I_DID memory.
    """
    surprise_threshold, affect_threshold = thresholds
    if outcome.surprise_delta < surprise_threshold:
        return None
    if outcome.affect > -affect_threshold:
        return None

    predecessor = repo.get(predecessor_id)
    if predecessor is None:
        raise RepoError(f"no predecessor with id {predecessor_id}")
    if predecessor.tier not in _STANCE_TIERS:
        raise RepoError(
            f"REGRET requires predecessor in {[t.value for t in _STANCE_TIERS]}, "
            f"got {predecessor.tier.value}"
        )
    if predecessor.source != SourceKind.I_DID:
        raise RepoError("REGRET predecessor must have source=i_did")
    if predecessor.superseded_by is not None:
        raise RepoError(
            f"predecessor {predecessor_id} already superseded; cannot mint REGRET"
        )

    regret = EpisodicMemory(
        memory_id=_new_id(),
        self_id=predecessor.self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content=f"regret for {predecessor_id}: {predecessor.content}",
        weight=clamp_weight(MemoryTier.REGRET, WEIGHT_BOUNDS[MemoryTier.REGRET][0]),
        affect=outcome.affect,
        confidence_at_creation=outcome.confidence_at_creation,
        surprise_delta=outcome.surprise_delta,
        intent_at_time=predecessor.intent_at_time,
        supersedes=predecessor.memory_id,
        immutable=True,
        created_at=now or datetime.now(UTC),
    )
    repo.insert(regret)
    repo.increment_contradiction_count(predecessor.memory_id)
    repo.set_superseded_by(predecessor.memory_id, regret.memory_id)
    return regret.memory_id


def handle_accomplishment_candidate(
    repo: Repo,
    self_id: str,
    content: str,
    intent: str,
    outcome: Outcome,
    *,
    now: datetime | None = None,
    thresholds: tuple[float, float] = (
        ACCOMPLISHMENT_SURPRISE_THRESHOLD,
        ACCOMPLISHMENT_AFFECT_THRESHOLD,
    ),
) -> str | None:
    """Mint an ACCOMPLISHMENT if thresholds are met. Returns new id or None."""
    surprise_threshold, affect_threshold = thresholds
    if outcome.surprise_delta < surprise_threshold:
        return None
    if outcome.affect < affect_threshold:
        return None
    if not intent:
        raise RepoError("ACCOMPLISHMENT requires non-empty intent")

    accomplishment = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.ACCOMPLISHMENT,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(
            MemoryTier.ACCOMPLISHMENT, WEIGHT_BOUNDS[MemoryTier.ACCOMPLISHMENT][0]
        ),
        affect=outcome.affect,
        confidence_at_creation=outcome.confidence_at_creation,
        surprise_delta=outcome.surprise_delta,
        intent_at_time=intent,
        immutable=True,
        created_at=now or datetime.now(UTC),
    )
    repo.insert(accomplishment)
    return accomplishment.memory_id


def handle_affirmation(
    repo: Repo,
    self_id: str,
    content: str,
    *,
    supersedes: str | None = None,
    now: datetime | None = None,
) -> str:
    """Mint an AFFIRMATION. Revocable (immutable=False); later supersedes chain."""
    affirmation = EpisodicMemory(
        memory_id=_new_id(),
        self_id=self_id,
        tier=MemoryTier.AFFIRMATION,
        source=SourceKind.I_DID,
        content=content,
        weight=clamp_weight(
            MemoryTier.AFFIRMATION, WEIGHT_BOUNDS[MemoryTier.AFFIRMATION][0]
        ),
        supersedes=supersedes,
        immutable=False,
        created_at=now or datetime.now(UTC),
    )
    repo.insert(affirmation)
    if supersedes is not None:
        repo.set_superseded_by(supersedes, affirmation.memory_id)
    return affirmation.memory_id
