"""Tuning: coefficients as AFFIRMATIONs. See specs/tuning.md.

Coefficients are held in a `CoefficientTable` dataclass. Runtime state is
loaded by applying every non-superseded `coefficient_commitment` AFFIRMATION
(in creation order) to a baseline seed table. A `CoefficientTuner` submits a
P15 candidate periodically; when dispatched, it reads recent observations
and proposes updates as new AFFIRMATIONs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


logger = logging.getLogger("turing.tuning")

from .motivation import (
    PRESSURE_MAX,
    BacklogItem,
    DispatchObservation,
    Motivation,
    priority_base,
)
from .reactor import Reactor
from .repo import Repo
from .tiers import WEIGHT_BOUNDS
from .types import EpisodicMemory, MemoryTier, SourceKind
from .write_paths import handle_affirmation


COEFFICIENT_COMMITMENT_PREFIX: str = "coefficient_commitment:"


# --- CoefficientTable -----------------------------------------------------


@dataclass(frozen=True)
class CoefficientTable:
    """Every runtime-tunable number in one place.

    Seed values are starting points; any deployment running under seeds for
    long should be considered under-tuned.
    """

    pressure_max: float = 5_000.0
    pressure_rate_coefficient: float = 1.0
    action_cadence_ticks: int = 10
    top_x: int = 5
    max_concurrent_dispatches: int = 4
    daydream_fire_floor: float = 10.0
    daydream_tokens_per_pass: int = 2_000
    daydream_writes_per_pass: int = 5
    daydream_micro_pass_max_ms: int = 500
    accomplishment_bias: float = 0.5
    regret_surprise_threshold: float = 0.4
    regret_affect_threshold: float = 0.3
    accomplishment_surprise_threshold: float = 0.3
    accomplishment_affect_threshold: float = 0.3
    tuner_cadence_minutes: int = 60
    tuner_observation_window: int = 10_000
    observation_retention_days: int = 30
    default_prepare_window_s: int = 600
    daydream_quiet_multiple: int = 5

    @classmethod
    def seed(cls) -> "CoefficientTable":
        return cls()

    @classmethod
    def from_repo(cls, repo: Repo, self_id: str) -> "CoefficientTable":
        """Load seed, then apply non-superseded coefficient_commitment AFFIRMATIONs.

        Any AFFIRMATION whose content does not parse as a valid update, or
        whose resulting value is outside the documented range, is skipped.
        The table falls back to the last valid state.
        """
        table = cls.seed()
        commitments = [
            m
            for m in repo.find(
                self_id=self_id,
                tier=MemoryTier.AFFIRMATION,
                source=SourceKind.I_DID,
                include_superseded=False,
            )
            if m.content.startswith(COEFFICIENT_COMMITMENT_PREFIX)
        ]
        commitments.sort(key=lambda m: m.created_at)
        for a in commitments:
            try:
                update = parse_coefficient_commitment(a.content)
            except (ValueError, TypeError):
                continue
            candidate = apply_update(table, update)
            if validate_table(candidate):
                table = candidate
        return table


# --- Parsing & updating ---------------------------------------------------


@dataclass(frozen=True)
class CoefficientUpdate:
    name: str
    value: Any

    def to_content(self) -> str:
        return f"{COEFFICIENT_COMMITMENT_PREFIX} {self.name} = {self.value}"


def parse_coefficient_commitment(content: str) -> CoefficientUpdate:
    if not content.startswith(COEFFICIENT_COMMITMENT_PREFIX):
        raise ValueError(f"not a coefficient commitment: {content!r}")
    body = content[len(COEFFICIENT_COMMITMENT_PREFIX) :].strip()
    name, sep, value_str = body.partition("=")
    if not sep:
        raise ValueError(f"missing '=' in commitment: {body!r}")
    name = name.strip()
    value_str = value_str.strip()
    parsed: Any
    if "." in value_str:
        parsed = float(value_str)
    else:
        try:
            parsed = int(value_str)
        except ValueError:
            parsed = float(value_str)
    return CoefficientUpdate(name=name, value=parsed)


def apply_update(table: CoefficientTable, update: CoefficientUpdate) -> CoefficientTable:
    field_names = {f.name for f in fields(table)}
    if update.name not in field_names:
        raise ValueError(f"unknown coefficient: {update.name!r}")
    return replace(table, **{update.name: update.value})


_DOCUMENTED_RANGES: dict[str, tuple[float, float]] = {
    "pressure_max": (0.0, 1e9),
    "pressure_rate_coefficient": (0.0, 1e6),
    "daydream_fire_floor": (0.0, 1e6),
    "daydream_tokens_per_pass": (1, 1_000_000),
    "daydream_writes_per_pass": (1, 10_000),
    "accomplishment_bias": (0.0, 1.0),
    "regret_surprise_threshold": (0.0, 1.0),
    "regret_affect_threshold": (0.0, 1.0),
    "accomplishment_surprise_threshold": (0.0, 1.0),
    "accomplishment_affect_threshold": (0.0, 1.0),
    "action_cadence_ticks": (1, 100_000),
    "top_x": (1, 10_000),
    "max_concurrent_dispatches": (1, 10_000),
    "tuner_cadence_minutes": (1, 10_000),
    "tuner_observation_window": (1, 1_000_000_000),
    "observation_retention_days": (1, 10_000),
    "default_prepare_window_s": (1, 10_000_000),
    "daydream_quiet_multiple": (1, 10_000),
    "daydream_micro_pass_max_ms": (1, 10_000_000),
}


def validate_table(table: CoefficientTable) -> bool:
    for f in fields(table):
        if f.name in _DOCUMENTED_RANGES:
            lo, hi = _DOCUMENTED_RANGES[f.name]
            value = getattr(table, f.name)
            if not lo <= value <= hi:
                return False
    return True


# --- Tuner ----------------------------------------------------------------


class CoefficientTuner:
    """A P15 RASO producer that proposes coefficient AFFIRMATIONs.

    Submits a `tuning_candidate` BacklogItem on a cadence. On dispatch, reads
    recent dispatch observations and proposes coefficient updates that meet
    a significance threshold. Proposed updates are committed as AFFIRMATIONs
    via the standard write-paths handler.
    """

    MIN_OBSERVATIONS_BEFORE_SUBMIT: int = 50

    def __init__(
        self,
        *,
        motivation: Motivation,
        reactor: Reactor,
        repo: Repo,
        self_id: str,
        cadence_ticks: int = 60_000,
        min_observations: int = 50,
        significance_effect: float = 2.0,
        min_observations_before_submit: int | None = None,
    ) -> None:
        self._motivation = motivation
        self._reactor = reactor
        self._repo = repo
        self._self_id = self_id
        self._cadence_ticks = cadence_ticks
        self._min_observations = min_observations
        self._significance_effect = significance_effect
        self._min_observations_before_submit = (
            min_observations_before_submit
            if min_observations_before_submit is not None
            else self.MIN_OBSERVATIONS_BEFORE_SUBMIT
        )
        self._last_submitted_tick = 0
        self._signal_fns: list[Callable[[list[DispatchObservation]], list[CoefficientUpdate]]] = [
            self._analyze_pool_utilization,
            self._analyze_daydream_fire_rate,
        ]
        self._pending: list[Future[list[CoefficientUpdate]]] = []

        motivation.register_dispatch("tuning_candidate", self._on_dispatch)
        reactor.register(self.on_tick)

    def on_tick(self, tick: int) -> None:
        self._collect_completed()
        if len(self._motivation.observations) < self._min_observations_before_submit:
            return
        if tick - self._last_submitted_tick >= self._cadence_ticks:
            self._last_submitted_tick = tick
            self._motivation.insert(self._build_candidate())

    # ---- Candidate

    def _build_candidate(self) -> BacklogItem:
        return BacklogItem(
            item_id=str(uuid4()),
            class_=15,
            kind="tuning_candidate",
            payload={"self_id": self._self_id},
            fit={"general": 0.7},
            readiness=lambda s: True,
            cost_estimate_tokens=5_000,
        )

    def _on_dispatch(self, item: BacklogItem, chosen_pool: str) -> None:
        observations = list(self._motivation.observations)
        signal_fns = list(self._signal_fns)

        def _analyze() -> list[CoefficientUpdate]:
            proposals: list[CoefficientUpdate] = []
            for fn in signal_fns:
                proposals.extend(fn(observations))
            return proposals

        future = self._reactor.spawn(_analyze)
        self._pending.append(future)
        self._collect_completed()

    def _collect_completed(self) -> None:
        remaining: list[Future[list[CoefficientUpdate]]] = []
        for future in self._pending:
            if not future.done():
                remaining.append(future)
                continue
            try:
                proposals = future.result()
            except Exception:
                logger.exception("tuner analysis failed")
                continue
            for p in proposals:
                prior = self._find_prior(p.name)
                if prior is not None:
                    existing_val = parse_coefficient_commitment(prior.content).value
                    if abs(existing_val - p.value) < 0.01:
                        continue
                handle_affirmation(
                    self._repo,
                    self._self_id,
                    content=p.to_content(),
                    supersedes=prior.memory_id if prior is not None else None,
                )
        self._pending = remaining

    # ---- Signal analyses

    def _analyze_pool_utilization(
        self, observations: list[DispatchObservation]
    ) -> list[CoefficientUpdate]:
        """If one pool is chosen far more than others, raise its pressure coefficient.

        Placeholder heuristic: counts chosen_pool frequency. In the research
        sketch, this is expected to be crude. The point is to demonstrate the
        AFFIRMATION commitment path end-to-end.
        """
        if len(observations) < self._min_observations:
            return []
        counts: dict[str, int] = {}
        for o in observations:
            if o.chosen_pool:
                counts[o.chosen_pool] = counts.get(o.chosen_pool, 0) + 1
        if not counts:
            return []
        dominant_pool, dominant_count = max(counts.items(), key=lambda kv: kv[1])
        total = sum(counts.values())
        if dominant_count / total > 0.8:
            # Dominant pool is getting almost all the dispatch; this could
            # indicate over-aggressive pressure. Propose lowering
            # pressure_rate_coefficient slightly.
            return [CoefficientUpdate(name="pressure_rate_coefficient", value=0.9)]
        return []

    def _analyze_daydream_fire_rate(
        self, observations: list[DispatchObservation]
    ) -> list[CoefficientUpdate]:
        if len(observations) < self._min_observations:
            return []
        daydream_count = sum(1 for o in observations if o.kind == "daydream_candidate")
        rate = daydream_count / len(observations)
        if rate > 0.5:
            return [CoefficientUpdate(name="daydream_fire_floor", value=20.0)]
        if rate < 0.01:
            return [CoefficientUpdate(name="daydream_fire_floor", value=5.0)]
        return []

    # ---- Prior lookup

    def _find_prior(self, coefficient_name: str) -> EpisodicMemory | None:
        target_prefix = f"{COEFFICIENT_COMMITMENT_PREFIX} {coefficient_name} ="
        candidates = [
            m
            for m in self._repo.find(
                self_id=self._self_id,
                tier=MemoryTier.AFFIRMATION,
                source=SourceKind.I_DID,
                include_superseded=False,
            )
            if m.content.startswith(target_prefix)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda m: m.created_at, reverse=True)
        return candidates[0]
