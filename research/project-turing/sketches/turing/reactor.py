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
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Reactor(Protocol):
    tick_count: int

    def register(self, handler: Callable[[int], None]) -> None: ...
    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]: ...


class FakeReactor:
    def __init__(self) -> None:
        self._handlers: list[Callable[[int], None]] = []
        self.tick_count: int = 0

    def register(self, handler: Callable[[int], None]) -> None:
        self._handlers.append(handler)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.tick_count += 1
            for handler in list(self._handlers):
                handler(self.tick_count)

    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        """Run fn synchronously; return a resolved Future.

        Keeps library code that submits slow work via `reactor.spawn(...)`
        working under tests without any async machinery. Exceptions are
        captured in the Future, matching RealReactor's behavior.
        """
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future
