"""Reactor — unified 1000Hz event loop for proactive triggers.

Replaces scattered inline hooks and periodic heartbeats with a single
evaluation loop. The loop does NO I/O — it evaluates trigger conditions
(pure logic) and spawns async tasks for matches.

Benchmarked: 0.46% of 1 core, 35us blocking latency, 80KB for 100 triggers.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from stronghold.types.reactor import (
    Event,
    MutableEvent,
    ReactorStatus,
    TriggerMode,
    TriggerSpec,
    TriggerState,
)

logger = logging.getLogger("stronghold.reactor")


# ── Protocol for trigger actions ─────────────────────────────────


@runtime_checkable
class TriggerAction(Protocol):
    """Any callable that handles a trigger fire."""

    async def __call__(self, event: Event) -> dict[str, Any]: ...


# ── Reactor ──────────────────────────────────────────────────────


class Reactor:
    """1000Hz event loop. Pure condition evaluation + async dispatch.

    Usage::

        reactor = Reactor()
        reactor.register(spec, action)
        await reactor.start()  # runs forever

        reactor.emit(Event("post_tool_loop", {...}))
        result = await reactor.emit_and_wait(Event("pre_tool_call", {...}))
    """

    def __init__(self, tick_hz: int = 1000) -> None:
        self._tick_interval: float = 1.0 / tick_hz
        self._triggers: list[tuple[TriggerState, TriggerAction]] = []
        self._queue: asyncio.Queue[MutableEvent] = asyncio.Queue()
        self._running: bool = False
        self._tick_count: int = 0
        self._active_tasks: set[asyncio.Task[None]] = set()
        self._event_log: deque[dict[str, str]] = deque(maxlen=500)
        self._events_processed: int = 0
        self._triggers_fired: int = 0
        self._tasks_completed: int = 0
        self._tasks_failed: int = 0

    # ── Registration ─────────────────────────────────────────

    def register(self, spec: TriggerSpec, action: TriggerAction) -> None:
        """Register a trigger with its action handler."""
        state = TriggerState(spec=spec)
        self._triggers.append((state, action))
        logger.info("Trigger registered: %s [%s]", spec.name, spec.mode.value)

    def unregister(self, name: str) -> bool:
        """Remove a trigger by name. Returns True if found."""
        before = len(self._triggers)
        self._triggers = [(s, a) for s, a in self._triggers if s.spec.name != name]
        return len(self._triggers) < before

    # ── Emission ─────────────────────────────────────────────

    def emit(self, event: Event) -> None:
        """Non-blocking fire-and-forget."""
        self._queue.put_nowait(MutableEvent(name=event.name, data=event.data))

    async def emit_and_wait(self, event: Event, *, timeout: float = 5.0) -> dict[str, Any]:
        """Blocking emit — caller awaits the trigger result."""
        loop = asyncio.get_running_loop()
        mev = MutableEvent(
            name=event.name,
            data=event.data,
            future=loop.create_future(),
        )
        self._queue.put_nowait(mev)
        assert mev.future is not None  # for mypy
        return await asyncio.wait_for(mev.future, timeout=timeout)

    # ── Main loop ────────────────────────────────────────────

    async def start(self) -> None:
        """Run the reactor. Blocks until stop() is called."""
        self._running = True
        logger.info(
            "Reactor started: %d triggers, %d Hz",
            len(self._triggers),
            round(1 / self._tick_interval),
        )
        while self._running:
            tick_start = time.monotonic()
            await self._tick()
            elapsed = time.monotonic() - tick_start
            sleep_time = self._tick_interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def stop(self) -> None:
        """Stop the reactor loop."""
        self._running = False
        logger.info("Reactor stopped after %d ticks", self._tick_count)

    async def _tick(self) -> None:
        """One evaluation cycle."""
        # 1. Drain queue
        events: list[MutableEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # 2. Evaluate triggers
        now = datetime.now()
        mono = time.monotonic()

        for state, action in self._triggers:
            if not state.is_active:
                continue

            matched = self._evaluate(state, events, now, mono)
            if matched is None:
                continue

            state.last_fired = mono
            state.last_fired_date = now.strftime("%Y-%m-%d")
            state.fire_count += 1
            self._triggers_fired += 1

            # Convert MutableEvent → frozen Event for the action
            frozen = Event(name=matched.name, data=matched.data)

            if state.spec.blocking and matched.future is not None:
                await self._resolve_blocking(state, action, frozen, matched.future)
            else:
                task = asyncio.create_task(self._run_action(state, action, frozen))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)

        # 3. Finalize events
        for ev in events:
            self._events_processed += 1
            self._event_log.append(
                {"name": ev.name, "time": now.isoformat(timespec="milliseconds")}
            )
            # Resolve orphan blocking futures
            if ev.future is not None and not ev.future.done():
                ev.future.set_result({"status": "no_matching_trigger"})

        self._tick_count += 1

    # ── Condition evaluation (pure logic) ────────────────────

    def _evaluate(
        self,
        state: TriggerState,
        events: list[MutableEvent],
        now: datetime,
        mono: float,
    ) -> MutableEvent | None:
        spec = state.spec

        if spec.mode == TriggerMode.EVENT:
            pat = state._compiled_pattern
            if pat is None:
                return None
            for ev in events:
                if pat.match(ev.name):
                    return ev
            return None

        if spec.mode == TriggerMode.INTERVAL:
            effective_interval = spec.interval_secs
            if spec.jitter > 0 and state.last_fired > 0:
                effective_interval *= 1 + random.uniform(-spec.jitter, spec.jitter)
            if mono - state.last_fired >= effective_interval:
                return MutableEvent(name=f"_interval:{spec.name}")
            return None

        if spec.mode == TriggerMode.TIME:
            hhmm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            if hhmm == spec.at_time and state.last_fired_date != today:
                return MutableEvent(name=f"_time:{spec.name}")
            return None

        if spec.mode == TriggerMode.STATE:
            min_interval = max(spec.interval_secs, 10.0)
            if mono - state.last_fired >= min_interval:
                return MutableEvent(name=f"_state:{spec.name}")
            return None

        return None

    # ── Action execution ─────────────────────────────────────

    async def _resolve_blocking(
        self,
        state: TriggerState,
        action: TriggerAction,
        event: Event,
        future: asyncio.Future[dict[str, Any]],
    ) -> None:
        try:
            result = await action(event)
            future.set_result(result)
            state.consecutive_failures = 0
        except Exception as exc:
            future.set_exception(exc)
            self._circuit_break(state, exc)

    async def _run_action(self, state: TriggerState, action: TriggerAction, event: Event) -> None:
        try:
            await action(event)
            state.consecutive_failures = 0
            self._tasks_completed += 1
        except Exception as exc:
            self._tasks_failed += 1
            self._circuit_break(state, exc)

    def _circuit_break(self, state: TriggerState, exc: Exception) -> None:
        state.consecutive_failures += 1
        state.last_error = str(exc)[:300]
        logger.warning(
            "Trigger '%s' failed (%d/%d): %s",
            state.spec.name,
            state.consecutive_failures,
            state.spec.max_failures,
            exc,
        )
        if state.consecutive_failures >= state.spec.max_failures:
            state.disabled_by_breaker = True
            logger.error(
                "CIRCUIT BREAKER: '%s' disabled after %d failures",
                state.spec.name,
                state.consecutive_failures,
            )

    # ── Admin ────────────────────────────────────────────────

    def enable_trigger(self, name: str) -> bool:
        """Re-enable a trigger (resets circuit breaker)."""
        for state, _ in self._triggers:
            if state.spec.name == name:
                state.disabled_by_breaker = False
                state.consecutive_failures = 0
                state.enabled = True
                return True
        return False

    def disable_trigger(self, name: str) -> bool:
        """Manually disable a trigger."""
        for state, _ in self._triggers:
            if state.spec.name == name:
                state.enabled = False
                return True
        return False

    def get_status(self) -> ReactorStatus:
        """Snapshot for admin API."""
        return ReactorStatus(
            running=self._running,
            tick_count=self._tick_count,
            active_tasks=len(self._active_tasks),
            events_processed=self._events_processed,
            triggers_fired=self._triggers_fired,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            triggers=[
                {
                    "name": s.spec.name,
                    "mode": s.spec.mode.value,
                    "enabled": s.is_active,
                    "fire_count": s.fire_count,
                    "failures": s.consecutive_failures,
                    "blocking": s.spec.blocking,
                    "last_error": s.last_error or None,
                }
                for s, _ in self._triggers
            ],
            recent_events=list(self._event_log)[-30:],
        )
