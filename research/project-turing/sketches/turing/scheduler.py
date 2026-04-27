"""Scheduler for P0 delivery-deadline work.

See specs/scheduler.md. The scheduler tracks items with a delivery_time,
inserts them into the motivation backlog when their early-executable window
opens, and holds their output in a delivery_buffer until delivery_time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .motivation import BacklogItem, Motivation, PipelineState
from .reactor import Reactor


DEFAULT_PREPARE_WINDOW: timedelta = timedelta(minutes=10)
DEFAULT_ESTIMATED_DURATION: timedelta = timedelta(seconds=30)
DAYDREAM_QUIET_MULTIPLE: int = 5


@dataclass(frozen=True)
class ScheduledItem:
    item_id: str
    self_id: str
    delivery_time: datetime
    early_executable_start: datetime
    estimated_duration: timedelta
    payload: Any
    delivery_callback_name: str
    preferred_model: str | None = None
    fit: dict[str, float] = field(default_factory=dict)


@dataclass
class DeliveryRecord:
    delivery_time: datetime
    output: Any
    delivery_callback_name: str
    produced_at: datetime


class Scheduler:
    """Pending scheduled items + delivery buffer.

    Registers on the FakeReactor to be ticked each frame. Inserts items into
    motivation when their early_executable_start passes. Invokes the delivery
    callback when delivery_time arrives.
    """

    def __init__(
        self,
        reactor: Reactor,
        motivation: Motivation,
        callback_registry: dict[str, Callable[[Any], None]] | None = None,
        *,
        avg_daydream_duration: timedelta = timedelta(milliseconds=500),
    ) -> None:
        self._reactor = reactor
        self._motivation = motivation
        self._pending: dict[str, ScheduledItem] = {}
        self._inserted: set[str] = set()
        self._delivery_buffer: dict[str, DeliveryRecord] = {}
        self._callback_registry: dict[str, Callable[[Any], None]] = callback_registry or {}
        self._avg_daydream_duration = avg_daydream_duration

        motivation.register_dispatch("p0_scheduled", self._on_dispatch)
        reactor.register(self.on_tick)

    # ---- registration

    def schedule(self, item: ScheduledItem) -> None:
        self._pending[item.item_id] = item

    def register_callback(self, name: str, fn: Callable[[Any], None]) -> None:
        self._callback_registry[name] = fn

    # ---- reactor loop

    def on_tick(self, tick: int) -> None:
        now = datetime.now(UTC)
        self._promote_ready_items(now)
        self._flush_deliverables(now)

    def _promote_ready_items(self, now: datetime) -> None:
        for item_id, item in list(self._pending.items()):
            if item.early_executable_start <= now and item_id not in self._inserted:
                self._motivation.insert(self._to_backlog_item(item))
                self._inserted.add(item_id)

    def _flush_deliverables(self, now: datetime) -> None:
        for item_id, record in list(self._delivery_buffer.items()):
            if now >= record.delivery_time:
                callback = self._callback_registry.get(record.delivery_callback_name)
                if callback is None:
                    raise KeyError(
                        f"no delivery callback registered for {record.delivery_callback_name!r}"
                    )
                callback(record.output)
                del self._delivery_buffer[item_id]
                self._pending.pop(item_id, None)
                self._inserted.discard(item_id)

    # ---- integration with motivation

    def _to_backlog_item(self, item: ScheduledItem) -> BacklogItem:
        def _readiness(state: PipelineState) -> bool:
            return state.now >= item.early_executable_start

        return BacklogItem(
            item_id=item.item_id,
            class_=0,
            kind="p0_scheduled",
            payload=item,
            fit=dict(item.fit),
            readiness=_readiness,
            cost_estimate_tokens=0,
        )

    def _on_dispatch(self, backlog_item: BacklogItem, chosen_pool: str) -> None:
        """Default P0 dispatch: stash a placeholder output into the delivery buffer.

        Real execution would delegate to an executor that runs the scheduled
        task. For the research sketch, any test can subclass Scheduler or
        register a different handler on motivation.
        """
        scheduled: ScheduledItem = backlog_item.payload
        self._delivery_buffer[scheduled.item_id] = DeliveryRecord(
            delivery_time=scheduled.delivery_time,
            output=("produced", scheduled.payload, chosen_pool),
            delivery_callback_name=scheduled.delivery_callback_name,
            produced_at=datetime.now(UTC),
        )

    def produce_output(self, item_id: str, output: Any, now: datetime | None = None) -> None:
        """Test hook: stash a concrete output for a scheduled item."""
        scheduled = self._pending[item_id]
        self._delivery_buffer[item_id] = DeliveryRecord(
            delivery_time=scheduled.delivery_time,
            output=output,
            delivery_callback_name=scheduled.delivery_callback_name,
            produced_at=now or datetime.now(UTC),
        )

    # ---- quiet zones

    def quiet_zones(self) -> list[tuple[datetime, datetime]]:
        buffer = DAYDREAM_QUIET_MULTIPLE * self._avg_daydream_duration
        zones: list[tuple[datetime, datetime]] = []
        for item in self._pending.values():
            zones.append((item.early_executable_start - buffer, item.early_executable_start))
        for record in self._delivery_buffer.values():
            zones.append((record.delivery_time - buffer, record.delivery_time + buffer))
        return zones


def new_item_id() -> str:
    return str(uuid4())
