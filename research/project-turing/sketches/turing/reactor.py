"""A tickable FakeReactor for research-branch tests.

Mirrors the contract that real main.Reactor exposes to producers:
per-tick event dispatch to registered handlers, deterministic under
explicit tick() calls. Not a performance fixture; just a correctness fixture.

Also exposes `spawn(fn, *args)` matching RealReactor's API; the fake version
runs fn synchronously and returns a resolved Future, keeping library code
reactor-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Reactor(Protocol):
    tick_count: int

    def register(self, handler: Callable[[int], None]) -> None: ...
    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]: ...


@dataclass
class IntervalTrigger:
    name: str
    interval: timedelta
    handler: Callable[[], None]
    first_fire_at: Any | None = None
    fire_count: int = 0


class FakeReactor:
    def __init__(self) -> None:
        self._handlers: list[Callable[[int], None]] = []
        self._interval_triggers: dict[str, IntervalTrigger] = {}
        self.tick_count: int = 0

    def register(self, handler: Callable[[int], None]) -> None:
        self._handlers.append(handler)

    def register_interval_trigger(
        self,
        name: str,
        interval: timedelta,
        handler: Callable[[], None],
        first_fire_at: Any | None = None,
        idempotent: bool = False,
    ) -> IntervalTrigger:
        if idempotent and name in self._interval_triggers:
            return self._interval_triggers[name]
        trigger = IntervalTrigger(
            name=name,
            interval=interval,
            handler=handler,
            first_fire_at=first_fire_at,
        )
        self._interval_triggers[name] = trigger
        return trigger

    def unregister_trigger(self, name: str) -> None:
        self._interval_triggers.pop(name, None)

    def fire_trigger(self, name: str) -> None:
        trigger = self._interval_triggers.get(name)
        if trigger is not None:
            trigger.handler()
            trigger.fire_count += 1

    @property
    def triggers(self) -> dict[str, IntervalTrigger]:
        return dict(self._interval_triggers)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.tick_count += 1
            for handler in list(self._handlers):
                handler(self.tick_count)

    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future
