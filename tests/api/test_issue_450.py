"""Tests for stronghold.agents.strategies.builders_learning.BuildersLearningStrategy.

The original file (issue #450) was a fossil from the ruff-cleanup change:
it had six tests that all just did ``strategy = ...; assert strategy is not None``
with docstrings like "Verify no F841 violations exist in builders_learning.py".
None of them exercised any behaviour. This replacement drives the real
worker-dispatch fork (frank / mason / default) and verifies the
tool_executor wiring through the strategy's helpers.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.strategies.builders_learning import BuildersLearningStrategy
from tests.fakes import FakeLLMClient


@pytest.fixture
def llm() -> FakeLLMClient:
    fake = FakeLLMClient()
    fake.set_simple_response("done")
    return fake


class TestWorkerDispatch:
    """BuildersLearningStrategy.reason routes on the ``worker`` kwarg:
    ``frank`` and ``mason`` each run their enhanced flow, anything else
    falls through to plain ReAct."""

    async def test_unknown_worker_falls_through_to_react(
        self, llm: FakeLLMClient
    ) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy.reason(
            messages=[{"role": "user", "content": "hi"}],
            model="fake-model",
            llm=llm,
            worker="someone_else",
        )
        # ReAct passthrough must deliver the fake LLM's content.
        assert result.response == "done"
        assert result.done is True
        # The fallback path calls the LLM exactly once for a plain response.
        assert len(llm.calls) == 1

    async def test_frank_worker_executes_full_pipeline(
        self, llm: FakeLLMClient
    ) -> None:
        """Frank path runs repo recon + failure analysis, stores learning,
        then returns the React result unchanged."""
        strategy = BuildersLearningStrategy(enable_learning=True)
        result = await strategy.reason(
            messages=[{"role": "user", "content": "implement X"}],
            model="fake-model",
            llm=llm,
            worker="frank",
        )
        assert result.response == "done"
        assert result.done is True

    async def test_mason_worker_executes_full_pipeline(
        self, llm: FakeLLMClient
    ) -> None:
        strategy = BuildersLearningStrategy(enable_learning=True)
        result = await strategy.reason(
            messages=[{"role": "user", "content": "finish X"}],
            model="fake-model",
            llm=llm,
            worker="mason",
        )
        assert result.response == "done"
        assert result.done is True


class TestRepositoryReconnaissance:
    """_check_repository_state uses the tool_executor kwarg; without one
    it must return empty structures, not raise."""

    async def test_no_tool_executor_returns_empty_state(self) -> None:
        strategy = BuildersLearningStrategy()
        state = await strategy._check_repository_state()
        assert state == {"code": [], "tests": [], "failed_prs": []}

    async def test_with_tool_executor_collects_code_and_tests(self) -> None:
        captured: list[tuple[str, dict[str, Any]]] = []

        async def fake_executor(name: str, args: dict[str, Any]) -> str:
            captured.append((name, args))
            if "src/stronghold" in args.get("command", ""):
                return "src/stronghold/foo.py\nsrc/stronghold/bar.py"
            return "tests/test_foo.py"

        strategy = BuildersLearningStrategy()
        state = await strategy._check_repository_state(tool_executor=fake_executor)

        assert state["code"] == [
            "src/stronghold/foo.py",
            "src/stronghold/bar.py",
        ]
        assert state["tests"] == ["tests/test_foo.py"]
        # Must have called the executor exactly twice (code + tests).
        assert len(captured) == 2
        assert all(name == "shell" for name, _ in captured)

    async def test_executor_exception_is_swallowed(self) -> None:
        """Recon failures must never bubble — the strategy should log and
        keep going with an empty state so Frank's pipeline continues."""

        async def boom(name: str, args: dict[str, Any]) -> str:
            raise RuntimeError("github down")

        strategy = BuildersLearningStrategy()
        state = await strategy._check_repository_state(tool_executor=boom)
        assert state == {"code": [], "tests": [], "failed_prs": []}


class TestPRDiagnostics:
    """_run_pr_diagnostics runs ruff/mypy/pytest through the executor and
    classifies issues as critical when the output contains ``error`` or
    ``failed``."""

    async def test_no_tool_executor_reports_all_passed(self) -> None:
        strategy = BuildersLearningStrategy()
        diag = await strategy._run_pr_diagnostics()
        assert diag == {"all_passed": True, "issues": [], "has_critical_issues": False}

    async def test_clean_executor_output_reports_all_passed(self) -> None:
        async def clean(name: str, args: dict[str, Any]) -> str:
            return "All checks passed."

        strategy = BuildersLearningStrategy()
        diag = await strategy._run_pr_diagnostics(tool_executor=clean)
        assert diag["all_passed"] is True
        assert diag["has_critical_issues"] is False
        assert diag["issues"] == []

    async def test_ruff_error_flags_critical_issue(self) -> None:
        calls: list[str] = []

        async def exec_with_ruff_error(name: str, args: dict[str, Any]) -> str:
            calls.append(args["command"])
            if "ruff" in args["command"]:
                return "src/stronghold/foo.py:1: error: bad thing"
            return "clean"

        strategy = BuildersLearningStrategy()
        diag = await strategy._run_pr_diagnostics(tool_executor=exec_with_ruff_error)
        assert diag["has_critical_issues"] is True
        assert diag["all_passed"] is False
        assert any(msg.startswith("ruff:") for msg in diag["issues"])

    async def test_pytest_failure_flags_critical_issue(self) -> None:
        async def exec_with_pytest_failure(name: str, args: dict[str, Any]) -> str:
            if "pytest" in args["command"]:
                return "3 failed, 2 passed"
            return "clean"

        strategy = BuildersLearningStrategy()
        diag = await strategy._run_pr_diagnostics(
            tool_executor=exec_with_pytest_failure
        )
        assert diag["has_critical_issues"] is True
        assert any(msg.startswith("pytest:") for msg in diag["issues"])


class TestStrategyConstructor:
    """The strategy forwards its own tuning knobs (max_rounds,
    force_tool_first) to the wrapped ReactStrategy."""

    def test_max_rounds_forwarded_to_react(self) -> None:
        strategy = BuildersLearningStrategy(max_rounds=7, force_tool_first=True)
        assert strategy._react.max_rounds == 7
        assert strategy._react.force_tool_first is True

    def test_enable_learning_flag_controls_learning_store(
        self, llm: FakeLLMClient
    ) -> None:
        s_on = BuildersLearningStrategy(enable_learning=True)
        s_off = BuildersLearningStrategy(enable_learning=False)
        assert s_on.enable_learning is True
        assert s_off.enable_learning is False
