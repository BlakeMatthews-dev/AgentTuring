"""Motivation: priority ladder, pressure vector, scoring, backlog, dispatch.

See specs/motivation.md. Scoring is:

    score(item) = priority_base(class) + max(pressure ⊙ fit)
    chosen_model(item) = argmax(pressure ⊙ fit)

The max-component of the elementwise product is the pressure bonus; its
argmax is the chosen pool. Both from one pass.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .reactor import Reactor


# --- Priority ladder: anchored scale with log-linear interpolation --------

PRIORITY_ANCHORS: dict[int, float] = {
    0: 1_000_000.0,
    1: 750_000.0,
    2: 500_000.0,
    3: 250_000.0,
    4: 100_000.0,
    5: 50_000.0,
    10: 10_000.0,
    20: 1_000.0,
    30: 100.0,
    40: 10.0,
    50: 1.0,
    60: 0.1,
    70: 0.01,
}


def priority_base(p: int) -> float:
    """Log-linear interpolation between anchored values.

    Smaller p means higher priority. p <= 0 returns the P0 value; p >= 70
    returns the P70 value.
    """
    if p <= min(PRIORITY_ANCHORS):
        return PRIORITY_ANCHORS[min(PRIORITY_ANCHORS)]
    if p >= max(PRIORITY_ANCHORS):
        return PRIORITY_ANCHORS[max(PRIORITY_ANCHORS)]
    if p in PRIORITY_ANCHORS:
        return PRIORITY_ANCHORS[p]

    keys = sorted(PRIORITY_ANCHORS)
    lo = max(k for k in keys if k < p)
    hi = min(k for k in keys if k > p)
    log_lo = math.log10(PRIORITY_ANCHORS[lo])
    log_hi = math.log10(PRIORITY_ANCHORS[hi])
    t = (p - lo) / (hi - lo)
    return 10 ** (log_lo + t * (log_hi - log_lo))


# --- Configuration (seeds; all runtime-tunable via tuning.md) -------------

PRESSURE_MAX: float = 5_000.0
TICK_BUDGET_MS: int = 1
ACTION_CADENCE_TICKS: int = 10
TOP_X: int = 5
MAX_CONCURRENT_DISPATCHES: int = 4
DAYDREAM_FIRE_FLOOR: float = 10.0


# --- Pressure & backlog types --------------------------------------------

PressureVec = dict[str, float]


@dataclass
class PipelineState:
    now: datetime
    pressure: PressureVec
    quiet_zones: list[tuple[datetime, datetime]] = field(default_factory=list)

    def in_any_quiet_zone(self) -> bool:
        return any(start <= self.now <= end for start, end in self.quiet_zones)


@dataclass
class BacklogItem:
    item_id: str
    class_: int  # priority class; smaller = higher
    kind: str  # dispatched via registered handler
    payload: Any = None
    fit: dict[str, float] = field(default_factory=dict)
    readiness: Callable[["PipelineState"], bool] | None = None
    dynamic_priority: Callable[[PressureVec], float] | None = None
    cost_estimate_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DispatchObservation:
    item_id: str
    kind: str
    class_: int
    chosen_pool: str
    score: float
    pressure_snapshot: PressureVec
    fit_snapshot: dict[str, float]
    decided_at: datetime
    outcome: str = "pending"
    outcome_resolved_at: datetime | None = None


# --- Scoring --------------------------------------------------------------


def score(item: BacklogItem, pressure: PressureVec) -> tuple[float, str]:
    """Return (score, chosen_pool). `chosen_pool = ""` when no fit has nonzero pressure."""
    if item.dynamic_priority is not None:
        base = item.dynamic_priority(pressure)
    else:
        base = priority_base(item.class_)

    best_pool = ""
    best_bonus = 0.0
    for pool_name, pool_fit in item.fit.items():
        if pool_fit <= 0.0:
            continue
        bonus = pressure.get(pool_name, 0.0) * pool_fit
        if bonus > best_bonus:
            best_bonus = bonus
            best_pool = pool_name
    return base + best_bonus, best_pool


# --- Motivation component -------------------------------------------------


class Motivation:
    """Backlog, two loops, dispatch.

    Producers submit via `insert()`. Handlers are registered via
    `register_dispatch(kind, handler)`. The FakeReactor drives `on_tick()`.
    """

    def __init__(
        self,
        reactor: Reactor,
        *,
        action_cadence_ticks: int = ACTION_CADENCE_TICKS,
        top_x: int = TOP_X,
        max_concurrent: int = MAX_CONCURRENT_DISPATCHES,
    ) -> None:
        self._reactor = reactor
        self._backlog: dict[str, BacklogItem] = {}
        self._pressure: PressureVec = {}
        self._in_flight: set[str] = set()
        self._handlers: dict[str, Callable[[BacklogItem, str], None]] = {}
        self._state_provider: Callable[[], PipelineState] | None = None
        self._observations: list[DispatchObservation] = []
        self._action_cadence_ticks = action_cadence_ticks
        self._top_x = top_x
        self._max_concurrent = max_concurrent
        reactor.register(self.on_tick)

    # ---- public API

    def set_pressure(self, pool_name: str, value: float) -> None:
        self._pressure[pool_name] = max(0.0, min(PRESSURE_MAX, value))

    @property
    def pressure(self) -> PressureVec:
        return dict(self._pressure)

    def register_dispatch(
        self,
        kind: str,
        handler: Callable[[BacklogItem, str], None],
    ) -> None:
        self._handlers[kind] = handler

    def set_state_provider(self, provider: Callable[[], PipelineState]) -> None:
        self._state_provider = provider

    def insert(self, item: BacklogItem) -> str:
        self._backlog[item.item_id] = item
        return item.item_id

    def evict(self, item_id: str) -> None:
        self._backlog.pop(item_id, None)

    def get_backlog_item(self, item_id: str) -> BacklogItem | None:
        return self._backlog.get(item_id)

    @property
    def backlog(self) -> list[BacklogItem]:
        return list(self._backlog.values())

    @property
    def observations(self) -> list[DispatchObservation]:
        return list(self._observations)

    # ---- Reactor contract

    def on_tick(self, tick: int) -> None:
        if tick % self._action_cadence_ticks == 0:
            self._action_sweep()

    # ---- Action sweep

    def _action_sweep(self) -> None:
        state = self._current_state()
        scored: list[tuple[float, str, BacklogItem]] = []
        for item in self._backlog.values():
            if item.item_id in self._in_flight:
                continue
            score_val, chosen_pool = score(item, self._pressure)
            scored.append((score_val, chosen_pool, item))
        scored.sort(key=lambda t: -t[0])

        for score_val, chosen_pool, item in scored[: self._top_x]:
            if len(self._in_flight) >= self._max_concurrent:
                break
            if item.readiness is not None and not item.readiness(state):
                continue
            self._dispatch(item, chosen_pool, score_val)

    def _dispatch(self, item: BacklogItem, chosen_pool: str, score_val: float) -> None:
        handler = self._handlers.get(item.kind)
        if handler is None:
            raise ValueError(f"no dispatch handler registered for kind={item.kind!r}")
        self._in_flight.add(item.item_id)
        self._observations.append(
            DispatchObservation(
                item_id=item.item_id,
                kind=item.kind,
                class_=item.class_,
                chosen_pool=chosen_pool,
                score=score_val,
                pressure_snapshot=dict(self._pressure),
                fit_snapshot=dict(item.fit),
                decided_at=datetime.now(UTC),
            )
        )
        try:
            handler(item, chosen_pool)
        finally:
            self._in_flight.discard(item.item_id)
            self._backlog.pop(item.item_id, None)

    def _current_state(self) -> PipelineState:
        if self._state_provider is not None:
            return self._state_provider()
        return PipelineState(now=datetime.now(UTC), pressure=dict(self._pressure))
