"""Contradiction detector. See specs/detectors/contradiction.md.

Watches durable memory. When two durable memories with the same
`intent_at_time` hold opposing claims AND a later I_DID OBSERVATION supports
one side, submits a P14 candidate. When dispatched, mints a LESSON with
`supersedes` pointing at one parent and the other recorded in
`context["supersedes_via_lineage"]` per AC-C.1.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


logger = logging.getLogger("turing.detectors.contradiction")

from ..motivation import BacklogItem, Motivation, PipelineState
from ..reactor import Reactor
from ..repo import Repo
from ..tiers import WEIGHT_BOUNDS, clamp_weight
from ..types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind


CONTRADICTION_INDEX_MAX_PER_FAMILY: int = 200


# --- Structural checks ----------------------------------------------------


def _claims_opposed(a_content: str, b_content: str) -> bool:
    """Simple content-shape check. High precision, low recall, by design.

    The dispatched execution can run a more sophisticated check. Detection
    is meant to be cheap enough to run every tick.
    """
    a = a_content.lower().strip()
    b = b_content.lower().strip()
    if a == b:
        return False
    for true_suffix, false_suffix in [(" is true", " is false"), (" holds", " does not hold")]:
        if a.endswith(true_suffix) and b.endswith(false_suffix):
            return a[: -len(true_suffix)] == b[: -len(false_suffix)]
        if b.endswith(true_suffix) and a.endswith(false_suffix):
            return b[: -len(true_suffix)] == a[: -len(false_suffix)]
    if a == f"not {b}" or b == f"not {a}":
        return True
    return False


def _supports_one_side(c_content: str, a_content: str, b_content: str) -> bool:
    c = c_content.lower().strip()
    return c == a_content.lower().strip() or c == b_content.lower().strip()


# --- Payload & LLM stand-in -----------------------------------------------


@dataclass(frozen=True)
class ContradictionPayload:
    a_memory_id: str
    b_memory_id: str
    c_memory_id: str


@dataclass(frozen=True)
class DraftLesson:
    content: str
    initial_weight: float = 0.7
    origin_episode_id: str | None = None


class DraftLessonFn:
    """Stand-in for an LLM-backed lesson drafter.

    Real version would prompt a code-capable model; the sketch uses a
    deterministic function so tests are reproducible.
    """

    def __call__(self, a: EpisodicMemory, b: EpisodicMemory, c: EpisodicMemory) -> DraftLesson:
        return DraftLesson(
            content=f"resolution via {c.memory_id}: {c.content}",
            initial_weight=clamp_weight(MemoryTier.LESSON, 0.7),
            origin_episode_id=f"contradiction-{a.memory_id}-{b.memory_id}",
        )


default_draft_lesson: Callable[[EpisodicMemory, EpisodicMemory, EpisodicMemory], DraftLesson] = (
    DraftLessonFn()
)


# --- Detector -------------------------------------------------------------


class ContradictionDetector:
    """Cheap pairwise scan over durable memory; proposes LESSON-minting work.

    On each tick, loads durable memories created since the last scan, adds
    them to an in-memory family index, and checks for contradictions with
    previously-seen entries.
    """

    def __init__(
        self,
        *,
        repo: Repo,
        motivation: Motivation,
        reactor: Reactor,
        self_id: str,
        draft_lesson: Callable[
            [EpisodicMemory, EpisodicMemory, EpisodicMemory], DraftLesson
        ] = default_draft_lesson,
    ) -> None:
        self._repo = repo
        self._motivation = motivation
        self._reactor = reactor
        self._self_id = self_id
        self._draft_lesson = draft_lesson
        self._family_index: dict[str, list[str]] = {}  # intent → [memory_id, ...]
        self._submitted_keys: set[str] = set()
        self._last_scan_at: datetime | None = None
        self._pending: list[tuple[Future[Any], EpisodicMemory, EpisodicMemory, EpisodicMemory]] = []

        motivation.register_dispatch("raso_contradiction", self._on_dispatch)
        reactor.register(self.on_tick)

    # ---- Reactor hook

    def on_tick(self, tick: int) -> None:
        self._collect_completed()
        new_memories = self._load_new_durable()
        for m in new_memories:
            self._add_to_index(m)
            self._check(m)
        if new_memories:
            self._last_scan_at = max(m.created_at for m in new_memories)

    def _load_new_durable(self) -> list[EpisodicMemory]:
        results: list[EpisodicMemory] = []
        for m in self._repo.find(
            self_id=self._self_id,
            tiers=DURABLE_TIERS,
            source=SourceKind.I_DID,
            created_after=self._last_scan_at,
        ):
            results.append(m)
        return results

    def _add_to_index(self, m: EpisodicMemory) -> None:
        family = self._normalize_intent(m.intent_at_time)
        if not family:
            return
        bucket = self._family_index.setdefault(family, [])
        if m.memory_id not in bucket:
            bucket.append(m.memory_id)
            if len(bucket) > CONTRADICTION_INDEX_MAX_PER_FAMILY:
                bucket.pop(0)

    def _normalize_intent(self, intent: str) -> str:
        return intent.lower().strip()

    def _check(self, m: EpisodicMemory) -> None:
        family = self._normalize_intent(m.intent_at_time)
        if not family:
            return
        bucket = self._family_index.get(family, [])
        for other_id in bucket:
            if other_id == m.memory_id:
                continue
            other = self._repo.get(other_id)
            if other is None:
                continue
            if other.superseded_by is not None or m.superseded_by is not None:
                continue
            if not _claims_opposed(m.content, other.content):
                continue
            resolution = self._find_resolution(m, other)
            if resolution is None:
                continue
            key = self._dedup_key(m, other, resolution)
            if key in self._submitted_keys:
                continue
            self._submitted_keys.add(key)
            self._motivation.insert(self._build_candidate(m, other, resolution))

    def _find_resolution(self, a: EpisodicMemory, b: EpisodicMemory) -> EpisodicMemory | None:
        newest = max(a.created_at, b.created_at)
        for c in self._repo.find(
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            intent_at_time=a.intent_at_time,
            created_after=newest,
        ):
            if _supports_one_side(c.content, a.content, b.content):
                return c
        return None

    def _dedup_key(self, a: EpisodicMemory, b: EpisodicMemory, c: EpisodicMemory) -> str:
        parts = sorted([a.memory_id, b.memory_id, c.memory_id])
        return "|".join(parts)

    def _build_candidate(
        self, a: EpisodicMemory, b: EpisodicMemory, c: EpisodicMemory
    ) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=14,
            kind="raso_contradiction",
            payload=ContradictionPayload(
                a_memory_id=a.memory_id,
                b_memory_id=b.memory_id,
                c_memory_id=c.memory_id,
            ),
            fit={"claude-code": 1.0, "gemini-pro": 0.7},
            readiness=self._readiness,
            cost_estimate_tokens=2_000,
        )

    def _readiness(self, state: PipelineState) -> bool:
        # Readiness relies on the payload's memories still being
        # non-superseded. Cheap check deferred to dispatch because it requires
        # a repo round-trip.
        return True

    # ---- Dispatch execution

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload: ContradictionPayload = item.payload
        a = self._repo.get(payload.a_memory_id)
        b = self._repo.get(payload.b_memory_id)
        c = self._repo.get(payload.c_memory_id)
        if any(m is None for m in (a, b, c)):
            return
        assert a is not None and b is not None and c is not None
        if a.superseded_by is not None or b.superseded_by is not None:
            return

        # Slow LLM-backed drafting runs off-tick. Collect on later tick
        # (or same tick under FakeReactor's synchronous spawn).
        future = self._reactor.spawn(self._draft_lesson, a, b, c)
        self._pending.append((future, a, b, c))
        self._collect_completed()

    def _collect_completed(self) -> None:
        remaining: list[tuple[Future[Any], EpisodicMemory, EpisodicMemory, EpisodicMemory]] = []
        for future, a, b, c in self._pending:
            if not future.done():
                remaining.append((future, a, b, c))
                continue
            try:
                draft = future.result()
            except Exception:
                logger.exception(
                    "contradiction draft failed for triple %s/%s/%s",
                    a.memory_id,
                    b.memory_id,
                    c.memory_id,
                )
                continue
            # Re-check staleness: another path may have superseded either parent.
            a_fresh = self._repo.get(a.memory_id)
            b_fresh = self._repo.get(b.memory_id)
            if a_fresh is None or b_fresh is None:
                continue
            if a_fresh.superseded_by is not None or b_fresh.superseded_by is not None:
                continue
            lesson = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                tier=MemoryTier.LESSON,
                source=SourceKind.I_DID,
                content=draft.content,
                weight=draft.initial_weight,
                intent_at_time=a.intent_at_time,
                supersedes=a.memory_id,
                origin_episode_id=draft.origin_episode_id,
                context={
                    "supersedes_via_lineage": [a.memory_id, b.memory_id],
                    "resolution_observation": c.memory_id,
                },
            )
            self._repo.insert(lesson)
            self._repo.set_superseded_by(a.memory_id, lesson.memory_id)
            self._repo.set_superseded_by(b.memory_id, lesson.memory_id)
        self._pending = remaining
