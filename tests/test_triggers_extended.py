"""Tests for the five trigger handlers not covered by test_new_modules_2.

Covers lines 50, 89, 169-185, 199-242, 256-288 of src/stronghold/triggers.py:

  - rate_limit_eviction: the "evicted > 0" debug log branch
  - security_rescan:     the "not verdict.clean" warning branch
  - rlhf_feedback:       the entire handler including lazy FeedbackLoop init
  - mason_dispatch:      full dispatch path + exception + skip-no-issue
  - mason_pr_review:     full review path + exception + skip-no-pr

Uses a SimpleNamespace-based fake container so the tests don't depend
on the full DI wiring — each test only attaches the attributes the
target handler actually reaches.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from stronghold.events import Reactor
from stronghold.triggers import register_core_triggers
from stronghold.types.reactor import Event


def _find_action(reactor: Reactor, name: str) -> Any:
    """Return the registered async action for a trigger by spec name."""
    for state, action in reactor._triggers:
        if state.spec.name == name:
            return action
    msg = f"trigger not registered: {name}"
    raise AssertionError(msg)


def _base_container(**extra: Any) -> SimpleNamespace:
    """Minimal fake container with the universal triggers dependencies."""
    warden = SimpleNamespace(
        scan=AsyncMock(return_value=SimpleNamespace(clean=True, flags=())),
    )
    rate_limiter = SimpleNamespace(
        _windows={},
        _evict_stale_keys=lambda _now: None,
    )
    outcome_store = SimpleNamespace(
        get_task_completion_rate=AsyncMock(return_value={"total": 0, "rate": 0.0}),
    )
    learning_store = SimpleNamespace()
    reactor = Reactor(tick_hz=100)
    ns = SimpleNamespace(
        reactor=reactor,
        warden=warden,
        rate_limiter=rate_limiter,
        outcome_store=outcome_store,
        learning_store=learning_store,
        learning_promoter=None,
        tournament=None,
        canary_manager=None,
    )
    for key, val in extra.items():
        setattr(ns, key, val)
    return ns


# ---------------------------------------------------------------------------
# rate_limit_eviction — debug log on eviction
# ---------------------------------------------------------------------------


class TestRateLimitEviction:
    @pytest.mark.asyncio
    async def test_no_evicted_keys_returns_zero(self) -> None:
        container = _base_container()
        register_core_triggers(container)
        action = _find_action(container.reactor, "rate_limit_eviction")
        result = await action(Event(name="_interval:rate_limit_eviction"))
        assert result == {"evicted": 0}

    @pytest.mark.asyncio
    async def test_evicted_keys_hits_debug_log_branch(self) -> None:
        """Simulate a rate limiter where eviction shrinks the window map."""
        shrinking = SimpleNamespace(_windows={"a": object(), "b": object()})

        def evict(_now: float) -> None:
            shrinking._windows.clear()

        shrinking._evict_stale_keys = evict
        container = _base_container(rate_limiter=shrinking)
        register_core_triggers(container)
        action = _find_action(container.reactor, "rate_limit_eviction")
        result = await action(Event(name="_interval:rate_limit_eviction"))
        assert result["evicted"] == 2


# ---------------------------------------------------------------------------
# security_rescan — verdict.clean=False branch
# ---------------------------------------------------------------------------


class TestSecurityRescanDirty:
    @pytest.mark.asyncio
    async def test_not_clean_verdict_logs_warning_and_returns_flags(self) -> None:
        dirty_warden = SimpleNamespace(
            scan=AsyncMock(
                return_value=SimpleNamespace(
                    clean=False,
                    flags=("prompt_injection", "secret_leak"),
                )
            )
        )
        container = _base_container(warden=dirty_warden)
        register_core_triggers(container)
        action = _find_action(container.reactor, "security_rescan")
        result = await action(
            Event(
                name="security.rescan",
                data={"content": "suspicious", "boundary": "tool_result"},
            )
        )
        assert result["clean"] is False
        assert "prompt_injection" in result["flags"]


# ---------------------------------------------------------------------------
# post_tool_learning — the "failure on tool_name" branch
# ---------------------------------------------------------------------------


class TestPostToolLearning:
    @pytest.mark.asyncio
    async def test_failure_with_tool_name_logs_and_returns(self) -> None:
        container = _base_container()
        register_core_triggers(container)
        action = _find_action(container.reactor, "post_tool_learning")
        result = await action(
            Event(
                name="post_tool_loop",
                data={"tool_name": "web_search", "success": False},
            )
        )
        assert result == {"tool_name": "web_search", "success": False}

    @pytest.mark.asyncio
    async def test_success_path_returns_true(self) -> None:
        container = _base_container()
        register_core_triggers(container)
        action = _find_action(container.reactor, "post_tool_learning")
        result = await action(
            Event(
                name="post_tool_loop",
                data={"tool_name": "file_ops", "success": True},
            )
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# rlhf_feedback — full handler path + skip branch
# ---------------------------------------------------------------------------


class TestRlhfFeedback:
    @pytest.mark.asyncio
    async def test_skip_when_no_review_result(self) -> None:
        container = _base_container()
        register_core_triggers(container)
        action = _find_action(container.reactor, "rlhf_feedback")
        result = await action(Event(name="pr.reviewed", data={}))
        assert result == {"skipped": True}

    @pytest.mark.asyncio
    async def test_lazy_initialisation_and_processing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First call should build _feedback_loop on the container and
        forward the review_result to process_review."""
        container = _base_container()
        register_core_triggers(container)
        action = _find_action(container.reactor, "rlhf_feedback")

        # Stub the FeedbackLoop class used inside the handler so construction
        # doesn't require real learning store plumbing.
        fake_loop = SimpleNamespace(process_review=AsyncMock(return_value=7))

        class _FakeFeedbackLoop:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            async def process_review(self, *args: Any, **kwargs: Any) -> int:
                return await fake_loop.process_review(*args, **kwargs)

        monkeypatch.setattr(
            "stronghold.agents.feedback.loop.FeedbackLoop",
            _FakeFeedbackLoop,
        )
        monkeypatch.setattr(
            "stronghold.agents.feedback.extractor.ReviewFeedbackExtractor",
            lambda: SimpleNamespace(),
        )
        monkeypatch.setattr(
            "stronghold.agents.feedback.tracker.InMemoryViolationTracker",
            lambda: SimpleNamespace(),
        )

        review = SimpleNamespace(findings=(), approved=True)
        result = await action(
            Event(name="pr.reviewed", data={"review_result": review})
        )
        assert result == {"stored_learnings": 7}
        assert hasattr(container, "_feedback_loop")  # cache populated
        fake_loop.process_review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reuses_cached_feedback_loop_on_second_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = _base_container()
        # Pre-populate the cached loop so the lazy-init branch is skipped.
        processed_calls: list[Any] = []

        async def _process(review: Any) -> int:
            processed_calls.append(review)
            return 2

        container._feedback_loop = SimpleNamespace(process_review=_process)
        register_core_triggers(container)
        action = _find_action(container.reactor, "rlhf_feedback")

        review = SimpleNamespace(findings=())
        result = await action(
            Event(name="pr.reviewed", data={"review_result": review})
        )
        assert result == {"stored_learnings": 2}
        assert len(processed_calls) == 1


# ---------------------------------------------------------------------------
# mason_dispatch — success + exception + skip paths
# ---------------------------------------------------------------------------


class _MasonQueue:
    """Tracks the state transitions Mason dispatch drives."""

    def __init__(self) -> None:
        self.started: list[int] = []
        self.completed: list[int] = []
        self.failed: list[tuple[int, str]] = []

    def start(self, issue: int) -> None:
        self.started.append(issue)

    def complete(self, issue: int) -> None:
        self.completed.append(issue)

    def fail(self, issue: int, error: str = "") -> None:
        self.failed.append((issue, error))


class TestMasonDispatch:
    @pytest.mark.asyncio
    async def test_skip_when_no_issue_number(self) -> None:
        container = _base_container(
            route_request=AsyncMock(),
            mason_queue=_MasonQueue(),
        )
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_dispatch")
        result = await action(Event(name="mason.issue_assigned", data={}))
        assert result == {"skipped": True}

    @pytest.mark.asyncio
    async def test_success_path_completes_issue(self) -> None:
        queue = _MasonQueue()
        route = AsyncMock(return_value={"ok": True})
        container = _base_container(route_request=route, mason_queue=queue)
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_dispatch")
        result = await action(
            Event(
                name="mason.issue_assigned",
                data={
                    "issue_number": 42,
                    "title": "Fix bug",
                    "owner": "acme",
                    "repo": "widgets",
                },
            )
        )
        assert result == {"issue_number": 42, "status": "completed"}
        assert queue.started == [42]
        assert queue.completed == [42]
        assert queue.failed == []
        route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_request_failure_marks_failed(self) -> None:
        queue = _MasonQueue()
        route = AsyncMock(side_effect=RuntimeError("llm offline"))
        container = _base_container(route_request=route, mason_queue=queue)
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_dispatch")
        result = await action(
            Event(
                name="mason.issue_assigned",
                data={
                    "issue_number": 7,
                    "title": "Break thing",
                    "owner": "acme",
                    "repo": "widgets",
                },
            )
        )
        assert result["status"] == "failed"
        assert "llm offline" in result["error"]
        assert queue.failed == [(7, "llm offline")]
        assert queue.completed == []


# ---------------------------------------------------------------------------
# mason_pr_review — success + exception + skip paths
# ---------------------------------------------------------------------------


class TestMasonPrReview:
    @pytest.mark.asyncio
    async def test_skip_when_no_pr_number(self) -> None:
        container = _base_container(route_request=AsyncMock())
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_pr_review")
        result = await action(
            Event(name="mason.pr_review_requested", data={})
        )
        assert result == {"skipped": True}

    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        route = AsyncMock(return_value={"ok": True})
        container = _base_container(route_request=route)
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_pr_review")
        result = await action(
            Event(
                name="mason.pr_review_requested",
                data={
                    "pr_number": 101,
                    "owner": "acme",
                    "repo": "widgets",
                },
            )
        )
        assert result == {"pr_number": 101, "status": "completed"}
        route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_path(self) -> None:
        route = AsyncMock(side_effect=RuntimeError("review boom"))
        container = _base_container(route_request=route)
        register_core_triggers(container)
        action = _find_action(container.reactor, "mason_pr_review")
        result = await action(
            Event(
                name="mason.pr_review_requested",
                data={
                    "pr_number": 202,
                    "owner": "acme",
                    "repo": "widgets",
                },
            )
        )
        assert result["status"] == "failed"
        assert "review boom" in result["error"]
