"""Tests for the Reactor event loop."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stronghold.events import Reactor
from stronghold.types.reactor import Event, TriggerMode, TriggerSpec


# ── Helpers ──────────────────────────────────────────────────────


class RecordingAction:
    """Fake action that records calls."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[Event] = []
        self.result = result or {"ok": True}

    async def __call__(self, event: Event) -> dict[str, Any]:
        self.calls.append(event)
        return self.result


class FailingAction:
    """Action that always raises."""

    def __init__(self, error: str = "boom") -> None:
        self.error = error

    async def __call__(self, event: Event) -> dict[str, Any]:
        raise RuntimeError(self.error)


async def run_reactor_briefly(reactor: Reactor, ticks: int = 50) -> None:
    """Run the reactor for a few ticks then stop."""

    async def _stop_after() -> None:
        for _ in range(ticks):
            await asyncio.sleep(0.002)
        reactor.stop()

    stop_task = asyncio.create_task(_stop_after())
    await reactor.start()
    await stop_task


# ── Event triggers ───────────────────────────────────────────────


async def test_event_trigger_fires_on_match() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="test", mode=TriggerMode.EVENT, event_pattern="my_event"),
        action,
    )

    reactor.emit(Event("my_event", {"key": "val"}))
    await run_reactor_briefly(reactor, ticks=10)

    assert len(action.calls) == 1
    assert action.calls[0].name == "my_event"
    assert action.calls[0].data == {"key": "val"}


async def test_event_trigger_ignores_non_matching() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="test", mode=TriggerMode.EVENT, event_pattern="target"),
        action,
    )

    reactor.emit(Event("other_event"))
    await run_reactor_briefly(reactor, ticks=10)

    assert len(action.calls) == 0


async def test_event_trigger_regex_match() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="test", mode=TriggerMode.EVENT, event_pattern="pre_.*"),
        action,
    )

    reactor.emit(Event("pre_tool_call"))
    reactor.emit(Event("post_tool_call"))
    await run_reactor_briefly(reactor, ticks=10)

    assert len(action.calls) == 1
    assert action.calls[0].name == "pre_tool_call"


# ── Interval triggers ───────────────────────────────────────────


async def test_interval_trigger_fires() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="heartbeat", mode=TriggerMode.INTERVAL, interval_secs=0.01),
        action,
    )

    await run_reactor_briefly(reactor, ticks=30)

    # Should fire multiple times in 30 ticks at 0.01s interval
    assert len(action.calls) >= 2


async def test_interval_trigger_respects_interval() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="slow", mode=TriggerMode.INTERVAL, interval_secs=999),
        action,
    )

    await run_reactor_briefly(reactor, ticks=50)

    # First fire is immediate (last_fired=0), but won't fire again
    assert len(action.calls) == 1


# ── Blocking triggers ───────────────────────────────────────────


async def test_blocking_trigger_resolves_future() -> None:
    reactor = Reactor(tick_hz=500)
    gate_result = {"allow": True, "reason": "ok"}
    action = RecordingAction(result=gate_result)

    reactor.register(
        TriggerSpec(
            name="gate",
            mode=TriggerMode.EVENT,
            event_pattern="pre_tool_call",
            blocking=True,
        ),
        action,
    )

    # Start reactor in background
    reactor_task = asyncio.create_task(reactor.start())

    result = await reactor.emit_and_wait(Event("pre_tool_call", {"tool": "ha_control"}))

    assert result == gate_result
    assert len(action.calls) == 1

    reactor.stop()
    await reactor_task


async def test_blocking_unmatched_returns_no_matching() -> None:
    reactor = Reactor(tick_hz=500)

    # No triggers registered
    reactor_task = asyncio.create_task(reactor.start())

    result = await reactor.emit_and_wait(Event("unknown_event"))

    assert result == {"status": "no_matching_trigger"}

    reactor.stop()
    await reactor_task


# ── Circuit breaker ──────────────────────────────────────────────


async def test_circuit_breaker_disables_after_n_failures() -> None:
    reactor = Reactor(tick_hz=500)
    action = FailingAction("kaboom")

    reactor.register(
        TriggerSpec(
            name="fragile",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=3,
        ),
        action,
    )

    await run_reactor_briefly(reactor, ticks=50)

    state = reactor._triggers[0][0]
    assert state.disabled_by_breaker is True
    assert state.consecutive_failures >= 3
    assert "kaboom" in state.last_error


async def test_enable_trigger_resets_breaker() -> None:
    reactor = Reactor(tick_hz=500)
    action = FailingAction()

    reactor.register(
        TriggerSpec(
            name="fragile",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=2,
        ),
        action,
    )

    await run_reactor_briefly(reactor, ticks=30)
    assert reactor._triggers[0][0].disabled_by_breaker is True

    # Re-enable
    assert reactor.enable_trigger("fragile") is True
    state = reactor._triggers[0][0]
    assert state.disabled_by_breaker is False
    assert state.consecutive_failures == 0


# ── Registration / unregistration ────────────────────────────────


async def test_unregister_removes_trigger() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="removable", mode=TriggerMode.EVENT, event_pattern="x"),
        action,
    )
    assert len(reactor._triggers) == 1

    assert reactor.unregister("removable") is True
    assert len(reactor._triggers) == 0


async def test_unregister_returns_false_for_unknown() -> None:
    reactor = Reactor(tick_hz=500)
    assert reactor.unregister("nonexistent") is False


# ── Status ───────────────────────────────────────────────────────


async def test_status_reports_correctly() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="t1", mode=TriggerMode.EVENT, event_pattern="evt"),
        action,
    )

    reactor.emit(Event("evt"))
    await run_reactor_briefly(reactor, ticks=10)

    status = reactor.get_status()
    assert status.running is False  # stopped after run_reactor_briefly
    assert status.tick_count > 0
    assert status.events_processed >= 1
    assert status.triggers_fired >= 1
    assert len(status.triggers) == 1
    assert status.triggers[0]["name"] == "t1"


# ── Multiple triggers on same event ─────────────────────────────


async def test_multiple_triggers_same_event() -> None:
    reactor = Reactor(tick_hz=500)
    action1 = RecordingAction({"handler": 1})
    action2 = RecordingAction({"handler": 2})

    reactor.register(
        TriggerSpec(name="a", mode=TriggerMode.EVENT, event_pattern="shared"),
        action1,
    )
    reactor.register(
        TriggerSpec(name="b", mode=TriggerMode.EVENT, event_pattern="shared"),
        action2,
    )

    reactor.emit(Event("shared"))
    await run_reactor_briefly(reactor, ticks=10)

    assert len(action1.calls) == 1
    assert len(action2.calls) == 1


# ── Disable trigger ──────────────────────────────────────────────


async def test_disabled_trigger_does_not_fire() -> None:
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()

    reactor.register(
        TriggerSpec(name="off", mode=TriggerMode.EVENT, event_pattern="x"),
        action,
    )
    reactor.disable_trigger("off")

    reactor.emit(Event("x"))
    await run_reactor_briefly(reactor, ticks=10)

    assert len(action.calls) == 0
