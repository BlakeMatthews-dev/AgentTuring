"""Types for the Reactor event loop."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
from typing import Any


class TriggerMode(StrEnum):
    """How a trigger decides to fire."""

    EVENT = "event"
    INTERVAL = "interval"
    TIME = "time"
    STATE = "state"


@dataclass(frozen=True)
class Event:
    """An event flowing through the Reactor."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class MutableEvent:
    """Event with a future — used for blocking triggers where the emitter awaits a result."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future[dict[str, Any]] | None = None


@dataclass
class TriggerSpec:
    """Declarative trigger definition. Registered with the Reactor."""

    name: str
    mode: TriggerMode

    # EVENT mode: regex matched against event name
    event_pattern: str = ""

    # INTERVAL mode: seconds between fires
    interval_secs: float = 0.0

    # INTERVAL jitter: ±fraction (0.2 = ±20%)
    jitter: float = 0.0

    # TIME mode: "HH:MM" local time
    at_time: str = ""

    # If true, emitter awaits result via future
    blocking: bool = False

    # Circuit breaker threshold
    max_failures: int = 3


@dataclass
class TriggerState:
    """Mutable runtime state for a trigger. Managed by the Reactor."""

    spec: TriggerSpec
    enabled: bool = True
    disabled_by_breaker: bool = False
    consecutive_failures: int = 0
    fire_count: int = 0
    last_fired: float = 0.0
    last_fired_date: str = ""
    last_error: str = ""
    _compiled_pattern: re.Pattern[str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.spec.event_pattern:
            self._compiled_pattern = re.compile(self.spec.event_pattern)

    @property
    def is_active(self) -> bool:
        return self.enabled and not self.disabled_by_breaker


@dataclass(frozen=True)
class ReactorStatus:
    """Snapshot of Reactor state for admin API."""

    running: bool
    tick_count: int
    active_tasks: int
    events_processed: int
    triggers_fired: int
    tasks_completed: int
    tasks_failed: int
    triggers: list[dict[str, Any]]
    recent_events: list[dict[str, str]]
