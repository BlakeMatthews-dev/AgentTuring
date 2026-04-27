"""Daydreaming: per-model candidate producer of last resort.

See specs/daydreaming.md. This module exposes two things:

  DaydreamWriter — the only writer permitted during a daydream pass.
                   Structurally can only emit `source = I_IMAGINED` at
                   HYPOTHESIS or OBSERVATION tier. No API exists for
                   I_DID writes or durable tiers.

  DaydreamProducer — one per model pool. Submits a BacklogItem whose
                     `dynamic_priority` rises with its pool's pressure.
                     When dispatched, executes a bounded pass using
                     DaydreamWriter.
"""

from __future__ import annotations

import enum
import logging
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4


logger = logging.getLogger("turing.daydream")


class _Phase(enum.Enum):
    IDLE = "idle"
    CANDIDATE_QUEUED = "candidate_queued"
    IMAGINING = "imagining"


from .motivation import (
    DAYDREAM_FIRE_FLOOR,
    PRESSURE_MAX,
    BacklogItem,
    Motivation,
    PipelineState,
    PressureVec,
    priority_base,
    score,
)
from .reactor import Reactor
from .repo import Repo
from .tiers import WEIGHT_BOUNDS
from .types import EpisodicMemory, MemoryTier, SourceKind


DAYDREAM_TOKENS_PER_PASS: int = 2_000
DAYDREAM_WRITES_PER_PASS: int = 5
ACCOMPLISHMENT_BIAS: float = 0.5


# --- Writer ---------------------------------------------------------------


class DaydreamWriter:
    """Only API: write HYPOTHESIS or OBSERVATION at source=I_IMAGINED.

    No methods exist for durable tiers or I_DID sources. The locks are
    structural, not policy; they cannot be bypassed without editing this
    class.
    """

    def __init__(self, repo: Repo, self_id: str, session_id: str) -> None:
        self._repo = repo
        self._self_id = self_id
        self._session_id = session_id

    def write_hypothesis(
        self, content: str, intent: str, context: dict[str, Any] | None = None
    ) -> str:
        m = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.HYPOTHESIS,
            source=SourceKind.I_IMAGINED,
            content=content,
            weight=WEIGHT_BOUNDS[MemoryTier.HYPOTHESIS][0] + 0.05,
            intent_at_time=intent,
            origin_episode_id=self._session_id,
            context=context or {},
        )
        self._repo.insert(m)
        return m.memory_id

    def write_observation(self, content: str, context: dict[str, Any] | None = None) -> str:
        m = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_IMAGINED,
            content=content,
            weight=WEIGHT_BOUNDS[MemoryTier.OBSERVATION][0] + 0.05,
            origin_episode_id=self._session_id,
            context=context or {},
        )
        self._repo.insert(m)
        return m.memory_id


# --- Imagine function (pluggable) -----------------------------------------


class ImagineFn(Protocol):
    """Stand-in for a bounded LLM call. Tests pin this to a fake."""

    def __call__(
        self,
        seed: EpisodicMemory,
        retrieved: list[EpisodicMemory],
        pool_name: str,
    ) -> list[tuple[str, str, str]]:
        """Return a list of (tier_name, content, intent) triples.

        tier_name is "hypothesis" or "observation". intent is ignored for
        observation entries.
        """


def default_imagine(
    seed: EpisodicMemory,
    retrieved: list[EpisodicMemory],
    pool_name: str,
) -> list[tuple[str, str, str]]:
    """Trivial no-LLM imagine — useful only as a smoke test fallback."""
    return [
        (
            "hypothesis",
            f"what-if variant of {seed.memory_id} on {pool_name}",
            seed.intent_at_time or "generic-intent",
        )
    ]


# --- Producer -------------------------------------------------------------


@dataclass
class DaydreamPayload:
    pool_name: str
    self_id: str
    producer: "DaydreamProducer"
    seed_memory_id: str | None = None


class DaydreamProducer:
    """One producer per model pool. Submits a candidate when pressure > 0.

    The candidate carries `dynamic_priority = f(pool_pressure)`. Under low
    pressure the candidate's score stays below DAYDREAM_FIRE_FLOOR and it
    sits unfired in the backlog.
    """

    def __init__(
        self,
        pool_name: str,
        *,
        self_id: str,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        imagine: ImagineFn = default_imagine,
    ) -> None:
        self._pool_name = pool_name
        self._self_id = self_id
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._imagine = imagine
        self._active_candidate_id: str | None = None
        self._pending: list[tuple[Future[Any], EpisodicMemory, str]] = []
        self._cooldown_until_tick: int = 0

        motivation.register_dispatch("daydream_candidate", self._on_dispatch)
        reactor.register(self.on_tick)

    @property
    def phase(self) -> _Phase:
        if self._active_candidate_id is not None:
            return _Phase.CANDIDATE_QUEUED
        if self._pending:
            return _Phase.IMAGINING
        return _Phase.IDLE

    # ---- Reactor loop

    MIN_TICKS_BETWEEN_DISPATCHES: int = 600

    def on_tick(self, tick: int) -> None:
        self._collect_completed()
        if tick < self._cooldown_until_tick:
            return
        p = self._motivation.pressure.get(self._pool_name, 0.0)
        if p <= 0.0:
            self._evict_if_present()
            return
        if self.phase == _Phase.CANDIDATE_QUEUED:
            return
        if self.phase == _Phase.IMAGINING:
            return
        self._active_candidate_id = self._motivation.insert(self._build_candidate())
        logger.debug(
            "pool=%s submitted candidate %s phase=%s->%s",
            self._pool_name,
            self._active_candidate_id,
            _Phase.IDLE.value,
            _Phase.CANDIDATE_QUEUED.value,
        )

    # ---- Candidate construction

    def _build_candidate(self) -> BacklogItem:
        item_id = str(uuid4())
        return BacklogItem(
            item_id=item_id,
            class_=20,
            kind="daydream_candidate",
            payload=DaydreamPayload(
                pool_name=self._pool_name,
                self_id=self._self_id,
                producer=self,
            ),
            fit={self._pool_name: 1.0},
            readiness=self._readiness,
            dynamic_priority=self._dynamic_priority,
            cost_estimate_tokens=DAYDREAM_TOKENS_PER_PASS,
        )

    def _dynamic_priority(self, pressure: PressureVec) -> float:
        """Map pool pressure to a priority_base in the P99..P21 band.

        Low pressure → priority_base(P99) ≈ just above P100.
        High pressure → priority_base(P21) ≈ just below P20 floor.
        Never crosses into P20 under seed coefficients.
        """
        p = pressure.get(self._pool_name, 0.0)
        if p <= 0.0:
            return priority_base(99)
        class_f = 99.0 - 78.0 * min(p / PRESSURE_MAX, 1.0)
        return priority_base(int(class_f))

    def _readiness(self, state: PipelineState) -> bool:
        if state.in_any_quiet_zone():
            return False
        item = self._motivation.get_backlog_item(self._active_candidate_id or "")
        if item is None:
            return False
        score_val, _ = score(item, state.pressure)
        return score_val > DAYDREAM_FIRE_FLOOR

    def _evict_if_present(self) -> None:
        if self._active_candidate_id is not None:
            cid = self._active_candidate_id
            self._motivation.evict(cid)
            self._active_candidate_id = None
            logger.debug(
                "pool=%s evicted candidate %s phase=%s->%s",
                self._pool_name,
                cid,
                _Phase.CANDIDATE_QUEUED.value,
                self.phase.value,
            )

    # ---- Dispatch execution

    def _apply_cooldown(self) -> None:
        self._cooldown_until_tick = self._reactor.tick_count + self.MIN_TICKS_BETWEEN_DISPATCHES

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        payload: DaydreamPayload = item.payload
        if payload.producer is not self:
            return
        logger.debug(
            "pool=%s dispatching candidate %s phase=%s->%s",
            self._pool_name,
            item.item_id,
            _Phase.CANDIDATE_QUEUED.value,
            _Phase.IMAGINING.value,
        )
        self._active_candidate_id = None

        seed = self._select_seed()
        if seed is None:
            logger.debug("pool=%s no seed available; skipping daydream pass", self._pool_name)
            self._apply_cooldown()
            return

        retrieved = self._retrieve_related(seed)
        session_id = str(uuid4())
        future = self._reactor.spawn(self._imagine, seed, retrieved, self._pool_name)
        self._pending.append((future, seed, session_id))
        self._apply_cooldown()
        self._collect_completed()

    def _collect_completed(self) -> None:
        remaining: list[tuple[Future[Any], EpisodicMemory, str]] = []
        for future, seed, session_id in self._pending:
            if not future.done():
                remaining.append((future, seed, session_id))
                continue
            try:
                proposals = future.result()
            except Exception:
                logger.exception("daydream imagine failed for session %s", session_id)
                self._write_session_marker(session_id, writes=0, seed=seed)
                continue
            writer = DaydreamWriter(self._repo, self._self_id, session_id)
            writes = 0
            for tier_name, content, intent in proposals[:DAYDREAM_WRITES_PER_PASS]:
                if tier_name == "hypothesis":
                    writer.write_hypothesis(content=content, intent=intent)
                elif tier_name == "observation":
                    writer.write_observation(content=content)
                else:
                    logger.warning("unknown tier from imagine: %s", tier_name)
                    continue
                writes += 1
            self._write_session_marker(session_id, writes=writes, seed=seed)
        self._pending = remaining

    # ---- Pass helpers

    def _select_seed(self) -> EpisodicMemory | None:
        """Prefer unresolved REGRETs; counter-weight toward ACCOMPLISHMENT."""
        regrets = [
            m
            for m in self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.REGRET,
                include_superseded=False,
            )
            if m.superseded_by is None
        ]
        accomplishments = list(
            self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.ACCOMPLISHMENT,
                include_superseded=False,
            )
        )
        candidates = list(regrets) + list(accomplishments)
        if not candidates:
            return None
        return candidates[0]

    def _retrieve_related(self, seed: EpisodicMemory) -> list[EpisodicMemory]:
        return list(
            self._repo.find(
                self_id=self._self_id,
                intent_at_time=seed.intent_at_time,
                include_superseded=False,
            )
        )

    def _write_session_marker(
        self,
        session_id: str,
        *,
        writes: int,
        seed: EpisodicMemory | None,
    ) -> None:
        marker = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content=(
                f"daydream session {session_id} on pool={self._pool_name}, "
                f"writes={writes}, seed={seed.memory_id if seed else None}"
            ),
            weight=WEIGHT_BOUNDS[MemoryTier.OBSERVATION][0] + 0.05,
            origin_episode_id=session_id,
            created_at=datetime.now(UTC),
        )
        self._repo.insert(marker)
