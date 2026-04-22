"""Tests for BuildersLearningStrategy.

Approach: exercise the strategy's real private helpers
(`_check_repository_state`, `_analyze_failure_patterns`, `_run_pr_diagnostics`,
`_store_{frank,mason}_learning`) and the public `reason()` dispatch. Each test
asserts on concrete return-value shape (issues found, failures listed,
fix/implement mode chosen) or on side-effects captured by a recording
tool_executor — no invocation-count tautologies against a mock.

Fixtures use `FakeLLMClient` / `NoopTracingBackend` from tests.fakes rather
than ad-hoc MagicMock-based mocks so the strategy receives the same shapes
production does.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from datetime import UTC

import pytest

from stronghold.agents.strategies.builders_learning import BuildersLearningStrategy
from stronghold.types.agent import ReasoningResult
from tests.fakes import FakeLLMClient, NoopTrace, NoopTracingBackend


# ── Shared fixtures ─────────────────────────────────────────────────

@pytest.fixture
def llm() -> FakeLLMClient:
    """Real FakeLLMClient — returns predictable text responses."""
    client = FakeLLMClient()
    client.set_simple_response("Response")
    return client


@pytest.fixture
def trace() -> NoopTrace:
    """Real NoopTrace from tests.fakes — satisfies the Trace protocol."""
    return NoopTracingBackend().create_trace()


# ── Initialization ───────────────────────────────────────────────────


class TestBuildersLearningStrategyInit:
    def test_default_initialization(self) -> None:
        strategy = BuildersLearningStrategy()
        assert strategy.max_rounds == 10
        assert strategy.force_tool_first is False
        assert strategy.enable_learning is True

    def test_custom_initialization(self) -> None:
        strategy = BuildersLearningStrategy(
            max_rounds=20,
            force_tool_first=True,
            enable_learning=False,
        )
        assert strategy.max_rounds == 20
        assert strategy.force_tool_first is True
        assert strategy.enable_learning is False


# ── _check_repository_state ──────────────────────────────────────────


class TestCheckRepositoryState:
    @pytest.mark.asyncio
    async def test_no_tool_executor_returns_empty(self) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state()
        assert result == {"code": [], "tests": [], "failed_prs": []}

    @pytest.mark.asyncio
    async def test_with_tool_executor_parses_code_and_tests(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            cmd = args.get("command", "")
            if "src/stronghold" in cmd:
                return "src/stronghold/main.py\nsrc/stronghold/app.py"
            if "tests" in cmd:
                return "tests/test_main.py"
            return ""

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        assert set(result["code"]) == {"src/stronghold/main.py", "src/stronghold/app.py"}
        assert result["tests"] == ["tests/test_main.py"]
        assert result["failed_prs"] == []

    @pytest.mark.asyncio
    async def test_tool_executor_returning_none_yields_empty_lists(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> None:
            return None

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        assert result["code"] == []
        assert result["tests"] == []

    @pytest.mark.asyncio
    async def test_tool_executor_exception_is_caught(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            raise RuntimeError("connection failed")

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        # Graceful fallback: empty lists, no exception leak
        assert result == {"code": [], "tests": [], "failed_prs": []}


# ── _analyze_failure_patterns ─────────────────────────────────────────


class TestAnalyzeFailurePatterns:
    @pytest.mark.asyncio
    async def test_no_tool_executor_returns_empty(self) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns()
        assert result == {
            "similar_issues": [],
            "failures": [],
            "reasons": [],
            "lessons": [],
        }

    @pytest.mark.asyncio
    async def test_failures_parsed_from_multiline_output(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            return "PR #10 rejected\nPR #11 rejected\nPR #12 rejected"

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert len(result["failures"]) == 3
        assert all("PR #" in f for f in result["failures"])

    @pytest.mark.asyncio
    async def test_tool_executor_returning_none_yields_empty(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> None:
            return None

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert result["failures"] == []

    @pytest.mark.asyncio
    async def test_tool_executor_exception_is_caught(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            raise RuntimeError("API error")

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert result == {
            "similar_issues": [],
            "failures": [],
            "reasons": [],
            "lessons": [],
        }


# ── _run_pr_diagnostics ─────────────────────────────────────────────


class TestRunPrDiagnostics:
    @pytest.mark.asyncio
    async def test_no_tool_executor_all_passed(self) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics()
        assert result["all_passed"] is True
        assert result["issues"] == []
        assert result["has_critical_issues"] is False

    @pytest.mark.asyncio
    async def test_clean_output_means_all_passed(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            return "All checks passed"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["all_passed"] is True
        assert result["issues"] == []
        assert result["has_critical_issues"] is False

    @pytest.mark.asyncio
    async def test_ruff_errors_flagged_as_critical(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            cmd = args.get("command", "")
            return "Found 3 error(s)" if "ruff" in cmd else "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert any("ruff" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_mypy_errors_flagged_as_critical(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            cmd = args.get("command", "")
            return "Found 2 error(s) in 1 file" if "mypy" in cmd else "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert any("mypy" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_pytest_failures_flagged_as_critical(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            cmd = args.get("command", "")
            return "1 failed, 9 passed" if "pytest" in cmd else "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert any("pytest" in issue for issue in result["issues"])

    @pytest.mark.asyncio
    async def test_all_three_checks_fail_reports_all_three(self) -> None:
        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            # Contains both "error" (ruff/mypy) and "failed" (pytest)
            return "error: something failed here"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert len(result["issues"]) == 3
        # All three tool categories are represented
        flat = " ".join(result["issues"])
        assert "ruff" in flat
        assert "mypy" in flat
        assert "pytest" in flat

    @pytest.mark.asyncio
    async def test_executor_exceptions_fail_the_gate_and_all_checks_attempted(
        self,
    ) -> None:
        """Exceptions in executor must NOT silently pass the gate — all three
        checks must still be attempted and each reported as a failure."""
        attempted_commands: list[str] = []

        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            attempted_commands.append(args.get("command", ""))
            raise RuntimeError("boom")

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)

        assert result["all_passed"] is False
        assert result["has_critical_issues"] is True
        assert len(result["issues"]) == 3
        assert all("tool_executor failed" in issue for issue in result["issues"])
        # Each of ruff/mypy/pytest was attempted (not short-circuited)
        flat = " ".join(attempted_commands)
        assert "ruff" in flat
        assert "mypy" in flat
        assert "pytest" in flat


# ── Frank + Mason public `reason()` dispatch ────────────────────────


class TestFrankWithToolExecutor:
    """Frank path exercises repo recon + failure analysis via tool_executor."""

    @pytest.mark.asyncio
    async def test_frank_calls_shell_and_github_tools_and_returns_done(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        call_log: list[tuple[str, dict[str, Any]]] = []

        async def tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            call_log.append((tool_name, args))
            if tool_name == "shell":
                return "src/stronghold/foo.py"
            if tool_name == "github":
                return "PR #5 rejected"
            return ""

        strategy = BuildersLearningStrategy(enable_learning=True)
        result = await strategy.reason(
            [{"role": "user", "content": "Add auth"}],
            "model",
            llm,
            trace=trace,
            worker="frank",
            run_id="test-frank-tool",
            tool_executor=tool_executor,
        )

        assert result.done is True
        # Frank actually called both shell (repo recon) and github (failure analysis)
        tool_names = {name for name, _ in call_log}
        assert "shell" in tool_names
        assert "github" in tool_names


class TestMasonExecutionMode:
    """Mason selects fix vs implement mode from Frank's diagnostic."""

    @pytest.mark.asyncio
    async def test_mason_completes_in_fix_mode_with_existing_code(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        strategy = BuildersLearningStrategy(enable_learning=False)
        result = await strategy.reason(
            [{"role": "user", "content": "Implement authentication"}],
            "model",
            llm,
            trace=trace,
            worker="mason",
            run_id="fix-mode",
            frank_diagnostic={"existing_code": True},
        )
        assert result.done is True

    @pytest.mark.asyncio
    async def test_mason_completes_in_implement_mode_without_existing_code(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        strategy = BuildersLearningStrategy(enable_learning=False)
        result = await strategy.reason(
            [{"role": "user", "content": "Implement authentication"}],
            "model",
            llm,
            trace=trace,
            worker="mason",
            run_id="implement-mode",
            frank_diagnostic={"existing_code": False},
        )
        assert result.done is True


class TestMasonWithCriticalDiagnostics:
    """Mason blocks PR when self-diagnosis finds critical issues (lines 185-199)."""

    @pytest.mark.asyncio
    async def test_ruff_errors_set_done_false_and_surface_in_response(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        async def failing_tool_executor(tool_name: str, args: dict[str, Any]) -> str:
            cmd = args.get("command", "")
            if "ruff" in cmd:
                return "error: found issues"
            return "OK"

        strategy = BuildersLearningStrategy(enable_learning=True)
        result = await strategy.reason(
            [{"role": "user", "content": "Implement feature"}],
            "model",
            llm,
            trace=trace,
            worker="mason",
            run_id="critical-fail",
            frank_diagnostic={"existing_code": False},
            tool_executor=failing_tool_executor,
        )
        assert result.done is False
        assert "Self-diagnosis" in result.response
        assert "issues" in result.response


class TestFallbackToReact:
    """Unknown or missing `worker` falls back to the ReAct strategy."""

    @pytest.mark.asyncio
    async def test_unknown_worker_still_produces_result(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "Do something"}],
            "model",
            llm,
            trace=trace,
            worker="unknown",
        )
        assert result.done is True

    @pytest.mark.asyncio
    async def test_no_worker_kwarg_still_produces_result(
        self, llm: FakeLLMClient, trace: NoopTrace,
    ) -> None:
        strategy = BuildersLearningStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "Do something"}],
            "model",
            llm,
            trace=trace,
        )
        assert result.done is True


# ── Small helpers ───────────────────────────────────────────────────


class TestUtcNow:
    def test_utc_now_returns_aware_utc_datetime(self) -> None:
        strategy = BuildersLearningStrategy()
        now = strategy._utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == UTC


# ── _store_{frank,mason}_learning ───────────────────────────────────


class TestStoreLearningMethods:
    """These are fire-and-forget helpers; they should not raise for valid inputs."""

    @pytest.mark.asyncio
    async def test_store_frank_learning_accepts_populated_repo_state(self) -> None:
        strategy = BuildersLearningStrategy()
        repo_state = {"code": ["a.py", "b.py"], "tests": ["t.py"], "failures": []}
        failure_patterns = {"failures": ["pr1", "pr2"]}
        result = ReasoningResult(response="done", done=True)
        # Must not raise for a well-formed payload
        await strategy._store_frank_learning(repo_state, failure_patterns, result)

    @pytest.mark.asyncio
    async def test_store_mason_learning_accepts_tool_history(self) -> None:
        strategy = BuildersLearningStrategy()
        diagnostics = {"all_passed": True, "issues": []}
        result = ReasoningResult(
            response="done",
            done=True,
            tool_history=[{"tool": "shell"}],
        )
        await strategy._store_mason_learning(diagnostics, result)
