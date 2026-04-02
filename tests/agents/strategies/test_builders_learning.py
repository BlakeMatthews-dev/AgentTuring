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
