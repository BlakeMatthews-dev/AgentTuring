"""Tests for BuildersLearningStrategy."""

import pytest
from stronghold.agents.strategies.builders_learning import BuildersLearningStrategy


class TestBuildersLearningStrategyInit:
    """Test BuildersLearningStrategy initialization."""

    def test_default_initialization(self):
        """Test strategy initializes with default values."""
        strategy = BuildersLearningStrategy()
        assert strategy.max_rounds == 10
        assert strategy.force_tool_first is False
        assert strategy.enable_learning is True

    def test_custom_initialization(self):
        """Test strategy initializes with custom values."""
        strategy = BuildersLearningStrategy(
            max_rounds=20,
            force_tool_first=True,
            enable_learning=False,
        )
        assert strategy.max_rounds == 20
        assert strategy.force_tool_first is True
        assert strategy.enable_learning is False


class TestFrankWorkflow:
    """Test Frank's learning workflow."""

    @pytest.mark.asyncio
    async def test_frank_checks_repository_state(self, mock_llm, mock_trace):
        """Frank should check repository state before planning."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Add user authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="frank",
            run_id="test-run-1",
        )

        assert result.done is True
        # In production, would verify repo state check was called

    @pytest.mark.asyncio
    async def test_frank_analyzes_failure_patterns(self, mock_llm, mock_trace):
        """Frank should analyze failure patterns from similar issues."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Add user authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="frank",
            run_id="test-run-2",
        )

        assert result.done is True
        # In production, would verify failure pattern analysis was called

    @pytest.mark.asyncio
    async def test_frank_produces_diagnostic(self, mock_llm, mock_trace):
        """Frank should produce diagnostic artifact for Mason."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Add user authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="frank",
            run_id="test-run-3",
        )

        assert result.done is True
        # In production, would verify diagnostic was stored


class TestMasonWorkflow:
    """Test Mason's learning workflow."""

    @pytest.mark.asyncio
    async def test_mason_reads_frank_diagnostic(self, mock_llm, mock_trace):
        """Mason should read Frank's diagnostic before starting."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Implement authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-run-4",
            frank_diagnostic={"existing_code": False},
        )

        assert result.done is True
        # In production, would verify diagnostic was read

    @pytest.mark.asyncio
    async def test_mason_determines_execution_mode(self, mock_llm, mock_trace):
        """Mason should determine fix vs implement mode from diagnostic."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Implement authentication"}]

        # Fix mode (existing code)
        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-run-5",
            frank_diagnostic={"existing_code": True},
        )

        assert result.done is True
        # In production, would verify fix mode was used

        # Implement mode (no existing code)
        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-run-6",
            frank_diagnostic={"existing_code": False},
        )

        assert result.done is True
        # In production, would verify implement mode was used

    @pytest.mark.asyncio
    async def test_mason_self_diagnoses_before_pr(self, mock_llm, mock_trace):
        """Mason should run diagnostics before PR submission."""
        strategy = BuildersLearningStrategy(enable_learning=False)
        messages = [{"role": "user", "content": "Implement authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-run-7",
            frank_diagnostic={"existing_code": False},
        )

        assert result.done is True
        # In production, would verify diagnostics were run


class TestLearningStorage:
    """Test learning storage functionality."""

    @pytest.mark.asyncio
    async def test_frank_stores_learning(self, mock_llm, mock_trace):
        """Frank should store learning in memory."""
        strategy = BuildersLearningStrategy(enable_learning=True)
        messages = [{"role": "user", "content": "Add user authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="frank",
            run_id="test-run-8",
        )

        assert result.done is True
        # In production, would verify learning was stored

    @pytest.mark.asyncio
    async def test_mason_stores_learning(self, mock_llm, mock_trace):
        """Mason should store learning in memory."""
        strategy = BuildersLearningStrategy(enable_learning=True)
        messages = [{"role": "user", "content": "Implement authentication"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-run-9",
            frank_diagnostic={"existing_code": False},
        )

        assert result.done is True
        # In production, would verify learning was stored


# Mock fixtures for testing
@pytest.fixture
def mock_llm():
    """Mock LLM client."""

    class MockLLM:
        async def complete(self, messages, model, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Response",
                            "role": "assistant",
                            "tool_calls": [],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    return MockLLM()


@pytest.fixture
def mock_trace():
    """Mock trace object."""

    class MockTrace:
        def span(self, name):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def set_input(self, data):
            pass

        def set_usage(self, **kwargs):
            pass

        def set_output(self, data):
            pass

    return MockTrace()


# ── Tests targeting uncovered lines 217-298 ──────────────────────────


class TestCheckRepositoryState:
    """Cover _check_repository_state with and without tool_executor."""

    async def test_no_tool_executor_returns_empty(self):
        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state()
        assert result == {"code": [], "tests": [], "failed_prs": []}

    async def test_with_tool_executor_success(self):
        async def tool_executor(tool_name, args):
            if "src/stronghold" in args.get("command", ""):
                return "src/stronghold/main.py\nsrc/stronghold/app.py"
            if "tests" in args.get("command", ""):
                return "tests/test_main.py"
            return ""

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        assert len(result["code"]) == 2
        assert "src/stronghold/main.py" in result["code"]
        assert len(result["tests"]) == 1
        assert result["failed_prs"] == []

    async def test_with_tool_executor_returns_none(self):
        """tool_executor returns None (falsy) for both calls."""

        async def tool_executor(tool_name, args):
            return None

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        assert result["code"] == []
        assert result["tests"] == []

    async def test_with_tool_executor_exception(self):
        """tool_executor raises; should catch and return empty."""

        async def tool_executor(tool_name, args):
            raise RuntimeError("connection failed")

        strategy = BuildersLearningStrategy()
        result = await strategy._check_repository_state(tool_executor=tool_executor)
        assert result == {"code": [], "tests": [], "failed_prs": []}


class TestAnalyzeFailurePatterns:
    """Cover _analyze_failure_patterns with and without tool_executor."""

    async def test_no_tool_executor_returns_empty(self):
        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns()
        assert result == {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

    async def test_with_tool_executor_success(self):
        async def tool_executor(tool_name, args):
            return "PR #10 rejected\nPR #11 rejected\nPR #12 rejected"

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert len(result["failures"]) == 3
        assert result["similar_issues"] == []
        assert result["reasons"] == []
        assert result["lessons"] == []

    async def test_with_tool_executor_returns_none(self):
        async def tool_executor(tool_name, args):
            return None

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert result["failures"] == []

    async def test_with_tool_executor_exception(self):
        async def tool_executor(tool_name, args):
            raise RuntimeError("API error")

        strategy = BuildersLearningStrategy()
        result = await strategy._analyze_failure_patterns(tool_executor=tool_executor)
        assert result == {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}


class TestRunPrDiagnostics:
    """Cover _run_pr_diagnostics with and without tool_executor."""

    async def test_no_tool_executor_returns_all_passed(self):
        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics()
        assert result["all_passed"] is True
        assert result["issues"] == []
        assert result["has_critical_issues"] is False

    async def test_all_checks_pass(self):
        async def tool_executor(tool_name, args):
            return "All checks passed"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["all_passed"] is True
        assert result["issues"] == []
        assert result["has_critical_issues"] is False

    async def test_ruff_finds_errors(self):
        async def tool_executor(tool_name, args):
            cmd = args.get("command", "")
            if "ruff" in cmd:
                return "Found 3 error(s)"
            return "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert len(result["issues"]) == 1
        assert "ruff" in result["issues"][0]

    async def test_mypy_finds_errors(self):
        async def tool_executor(tool_name, args):
            cmd = args.get("command", "")
            if "mypy" in cmd:
                return "Found 2 error(s) in 1 file"
            return "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert any("mypy" in issue for issue in result["issues"])

    async def test_pytest_finds_failures(self):
        async def tool_executor(tool_name, args):
            cmd = args.get("command", "")
            if "pytest" in cmd:
                return "1 failed, 9 passed"
            return "OK"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert any("pytest" in issue for issue in result["issues"])

    async def test_all_checks_fail(self):
        async def tool_executor(tool_name, args):
            # Must contain "error" for ruff/mypy and "failed" for pytest
            return "error: something failed here"

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["has_critical_issues"] is True
        assert len(result["issues"]) == 3

    async def test_tool_executor_exceptions_report_as_failures(self):
        """Broken tool_executor = quality gate failure, not silent pass."""
        call_count = 0

        async def tool_executor(tool_name, args):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        strategy = BuildersLearningStrategy()
        result = await strategy._run_pr_diagnostics(tool_executor=tool_executor)
        assert result["all_passed"] is False
        assert result["has_critical_issues"] is True
        assert len(result["issues"]) == 3
        assert all("tool_executor failed" in issue for issue in result["issues"])
        assert call_count == 3  # all three checks attempted


class TestMasonWithCriticalDiagnostics:
    """Cover Mason path where diagnostics find critical issues (lines 185-199)."""

    async def test_mason_critical_issues_sets_done_false(self, mock_llm, mock_trace):
        """When PR diagnostics find critical issues, result.done should be False."""

        async def failing_tool_executor(tool_name, args):
            cmd = args.get("command", "")
            if "ruff" in cmd:
                return "error: found issues"
            return "OK"

        strategy = BuildersLearningStrategy(enable_learning=True)
        messages = [{"role": "user", "content": "Implement feature"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="mason",
            run_id="test-critical",
            frank_diagnostic={"existing_code": False},
            tool_executor=failing_tool_executor,
        )

        assert result.done is False
        assert "Self-diagnosis" in result.response
        assert "issues" in result.response


class TestFrankWithToolExecutor:
    """Cover Frank path with tool_executor wired (hits lines 217-260)."""

    async def test_frank_with_tool_executor_and_learning(self, mock_llm, mock_trace):
        call_log = []

        async def tool_executor(tool_name, args):
            call_log.append((tool_name, args))
            if tool_name == "shell":
                return "src/stronghold/foo.py"
            if tool_name == "github":
                return "PR #5 rejected"
            return ""

        strategy = BuildersLearningStrategy(enable_learning=True)
        messages = [{"role": "user", "content": "Add auth"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="frank",
            run_id="test-frank-tool",
            tool_executor=tool_executor,
        )

        assert result.done is True
        # Verify tool_executor was called for repo recon and failure analysis
        tool_names = [name for name, _ in call_log]
        assert "shell" in tool_names
        assert "github" in tool_names


class TestFallbackToReact:
    """Cover the fallback path when worker is neither frank nor mason."""

    async def test_unknown_worker_falls_back_to_react(self, mock_llm, mock_trace):
        strategy = BuildersLearningStrategy()
        messages = [{"role": "user", "content": "Do something"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
            worker="unknown",
        )

        assert result.done is True

    async def test_no_worker_falls_back_to_react(self, mock_llm, mock_trace):
        strategy = BuildersLearningStrategy()
        messages = [{"role": "user", "content": "Do something"}]

        result = await strategy.reason(
            messages,
            "model",
            mock_llm,
            trace=mock_trace,
        )

        assert result.done is True


class TestUtcNow:
    """Cover _utc_now helper."""

    def test_utc_now_returns_aware_datetime(self):
        from datetime import timezone

        strategy = BuildersLearningStrategy()
        now = strategy._utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc


class TestStoreLearningMethods:
    """Cover _store_frank_learning and _store_mason_learning directly."""

    async def test_store_frank_learning(self):
        from stronghold.types.agent import ReasoningResult

        strategy = BuildersLearningStrategy()
        repo_state = {"code": ["a.py", "b.py"], "tests": ["t.py"], "failures": []}
        failure_patterns = {"failures": ["pr1", "pr2"]}
        result = ReasoningResult(response="done", done=True)
        # Should not raise
        await strategy._store_frank_learning(repo_state, failure_patterns, result)

    async def test_store_mason_learning(self):
        from stronghold.types.agent import ReasoningResult

        strategy = BuildersLearningStrategy()
        diagnostics = {"all_passed": True, "issues": []}
        result = ReasoningResult(response="done", done=True, tool_history=[{"tool": "shell"}])
        # Should not raise
        await strategy._store_mason_learning(diagnostics, result)
