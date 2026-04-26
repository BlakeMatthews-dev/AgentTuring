"""WorkloadDriver: injects synthetic traffic so a running research-box has
observations to generate.

Reads a YAML scenario, drops BacklogItems into motivation on configured
cadences, synthesizes outcomes that mint REGRETs / ACCOMPLISHMENTs, and can
inject contradictory durable pairs for the contradiction detector.

Scenario shape (see scenarios/*.yaml):

    streams:
      - kind: p1_chat
        class_: 1
        every_seconds: 60
        jitter_seconds: 15
        fit: {gemini: 1.0}
        outcome_success_rate: 0.9
        outcome_affect_range: [-0.6, 0.8]
        outcome_surprise_range: [0.0, 0.8]
      - ...

    contradictions:                # optional: see scenarios/contradiction-injection.yaml
      - intent: route-writing-request
        a_content: "artificer fits here is true"
        b_content: "artificer fits here is false"
        c_content: "artificer fits here is false"
        after_seconds: 5
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ..motivation import BacklogItem, Motivation, PipelineState
from ..reactor import Reactor
from ..repo import Repo
from ..scheduler import Scheduler, ScheduledItem
from ..tiers import WEIGHT_BOUNDS
from ..types import EpisodicMemory, MemoryTier, SourceKind
from ..write_paths import (
    Outcome,
    handle_accomplishment_candidate,
    handle_regret_candidate,
)


logger = logging.getLogger("turing.runtime.workload")


# ---------------------------------------------------------------------- types


@dataclass(frozen=True)
class StreamSpec:
    kind: str  # "p1_chat" | "p3_wait" | ...
    class_: int
    every_seconds: float
    jitter_seconds: float = 0.0
    fit: dict[str, float] = field(default_factory=dict)
    outcome_success_rate: float = 0.8
    outcome_affect_range: tuple[float, float] = (-0.5, 0.7)
    outcome_surprise_range: tuple[float, float] = (0.0, 0.6)
    intent: str = ""


@dataclass(frozen=True)
class ContradictionInjection:
    intent: str
    a_content: str
    b_content: str
    c_content: str
    after_seconds: float


@dataclass(frozen=True)
class Scenario:
    streams: tuple[StreamSpec, ...]
    contradictions: tuple[ContradictionInjection, ...] = ()


# ------------------------------------------------------------------- loading


def load_scenario(path: str | Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text())
    streams = tuple(
        StreamSpec(
            kind=s["kind"],
            class_=int(s["class_"]),
            every_seconds=float(s["every_seconds"]),
            jitter_seconds=float(s.get("jitter_seconds", 0.0)),
            fit=dict(s.get("fit", {})),
            outcome_success_rate=float(s.get("outcome_success_rate", 0.8)),
            outcome_affect_range=tuple(s.get("outcome_affect_range", [-0.5, 0.7])),
            outcome_surprise_range=tuple(s.get("outcome_surprise_range", [0.0, 0.6])),
            intent=str(s.get("intent", "")),
        )
        for s in (raw.get("streams") or [])
    )
    contradictions = tuple(
        ContradictionInjection(
            intent=str(c["intent"]),
            a_content=str(c["a_content"]),
            b_content=str(c["b_content"]),
            c_content=str(c["c_content"]),
            after_seconds=float(c.get("after_seconds", 5.0)),
        )
        for c in (raw.get("contradictions") or [])
    )
    return Scenario(streams=streams, contradictions=contradictions)


# ------------------------------------------------------------------ driver


class WorkloadDriver:
    """Drops items into motivation on configured cadences; writes outcomes."""

    def __init__(
        self,
        *,
        scenario: Scenario,
        motivation: Motivation,
        reactor: Reactor,
        scheduler: Scheduler | None,
        repo: Repo,
        self_id: str,
        rng: random.Random | None = None,
    ) -> None:
        self._scenario = scenario
        self._motivation = motivation
        self._reactor = reactor
        self._scheduler = scheduler
        self._repo = repo
        self._self_id = self_id
        self._rng = rng or random.Random()
        self._next_emit_at: dict[str, datetime] = {}
        self._contradiction_deadline: dict[int, datetime] = {}
        self._contradiction_fired: set[int] = set()
        self._start_at = datetime.now(UTC)

        for stream in scenario.streams:
            # Emit on the first tick, then advance by the stream's interval.
            self._next_emit_at[stream.kind] = self._start_at
            motivation.register_dispatch(stream.kind, self._make_handler(stream))
        for idx, injection in enumerate(scenario.contradictions):
            self._contradiction_deadline[idx] = self._start_at + timedelta(
                seconds=injection.after_seconds
            )

        reactor.register(self.on_tick)

    def _interval(self, stream: StreamSpec) -> timedelta:
        base = stream.every_seconds
        jitter = stream.jitter_seconds
        delta = base + self._rng.uniform(-jitter, jitter)
        return timedelta(seconds=max(0.001, delta))

    def on_tick(self, tick: int) -> None:
        now = datetime.now(UTC)
        for stream in self._scenario.streams:
            if now >= self._next_emit_at[stream.kind]:
                self._emit(stream)
                self._next_emit_at[stream.kind] = now + self._interval(stream)
        for idx, injection in enumerate(self._scenario.contradictions):
            if idx in self._contradiction_fired:
                continue
            if now >= self._contradiction_deadline[idx]:
                self._inject_contradiction(injection)
                self._contradiction_fired.add(idx)

    def _emit(self, stream: StreamSpec) -> None:
        item = BacklogItem(
            item_id=str(uuid4()),
            class_=stream.class_,
            kind=stream.kind,
            payload={"intent": stream.intent, "stream": stream.kind},
            fit=dict(stream.fit),
            readiness=lambda s: True,
            cost_estimate_tokens=256,
        )
        self._motivation.insert(item)

    def _make_handler(self, stream: StreamSpec):
        def handler(item: BacklogItem, chosen_pool: str) -> None:
            self._handle_dispatch(stream, item, chosen_pool)

        return handler

    def _handle_dispatch(
        self,
        stream: StreamSpec,
        item: BacklogItem,
        chosen_pool: str,
    ) -> None:
        success = self._rng.random() < stream.outcome_success_rate
        affect = self._rng.uniform(*stream.outcome_affect_range)
        affect = abs(affect) if success else -abs(affect)
        surprise = self._rng.uniform(*stream.outcome_surprise_range)
        outcome = Outcome(
            affect=affect,
            surprise_delta=surprise,
            confidence_at_creation=0.5,
        )

        if success:
            handle_accomplishment_candidate(
                self._repo,
                self._self_id,
                content=f"successful {stream.kind} dispatch",
                intent=stream.intent or stream.kind,
                outcome=outcome,
            )
            return

        # Failure: mint a stance to supersede with a REGRET.
        stance = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OPINION,
            source=SourceKind.I_DID,
            content=f"expected {stream.kind} to succeed",
            weight=WEIGHT_BOUNDS[MemoryTier.OPINION][0] + 0.1,
            intent_at_time=stream.intent or stream.kind,
        )
        self._repo.insert(stance)
        handle_regret_candidate(self._repo, stance.memory_id, outcome)

    def _inject_contradiction(self, inj: ContradictionInjection) -> None:
        base = datetime.now(UTC)

        def _aff(content: str, offset: timedelta) -> str:
            m = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self._self_id,
                tier=MemoryTier.AFFIRMATION,
                source=SourceKind.I_DID,
                content=content,
                weight=WEIGHT_BOUNDS[MemoryTier.AFFIRMATION][0] + 0.1,
                intent_at_time=inj.intent,
                created_at=base + offset,
            )
            self._repo.insert(m)
            return m.memory_id

        # Space timestamps so the OBSERVATION is strictly after both parents
        # — the contradiction detector's _find_resolution requires
        # `created_at > max(a.created_at, b.created_at)`.
        _aff(inj.a_content, timedelta(0))
        _aff(inj.b_content, timedelta(milliseconds=1))

        resolution = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content=inj.c_content,
            weight=WEIGHT_BOUNDS[MemoryTier.OBSERVATION][0] + 0.1,
            intent_at_time=inj.intent,
            created_at=base + timedelta(milliseconds=2),
        )
        self._repo.insert(resolution)
        logger.info("injected contradiction triple intent=%r", inj.intent)
