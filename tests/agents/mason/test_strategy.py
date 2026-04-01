"""Tests for MasonStrategy — 8-phase evidence-driven TDD pipeline.

Uses FakeLLMClient from tests/fakes.py. No mocks.
"""

from __future__ import annotations

from typing import Any

from tests.fakes import FakeLLMClient
from stronghold.agents.mason.strategy import MasonStrategy
from stronghold.types.agent import AgentIdentity


def _make_identity(phases: list[dict[str, Any]] | None = None) -> AgentIdentity:
    """Build an AgentIdentity with optional phases."""
    return AgentIdentity(
        name="mason",
        reasoning_strategy="mason",
        phases=tuple(phases or []),
    )


def _llm_response(content: str) -> dict[str, Any]:
    """Build a standard LLM response dict."""
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def _tool_call_response(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build a response with a tool call."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{tool_name}",
                    "function": {
                        "name": tool_name,
                        "arguments": __import__("json").dumps(args),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


class TestSinglePassFallback:
    """When no phases are configured, falls back to single ReAct pass."""

    async def test_no_phases_returns_response(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_llm_response("Done — no phases"))
        strategy = MasonStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "Do something"}],
            "test-model",
            llm,
            identity=_make_identity(phases=[]),
        )
        assert result.done
        assert "no phases" in result.response.lower()

    async def test_no_identity_falls_back(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_llm_response("Fallback response"))
        strategy = MasonStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
        )
        assert result.done
        assert result.response == "Fallback response"


class TestPhaseExecution:
    """Phase pipeline execution."""

    async def test_single_phase_completes(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            # Phase 1, round 1: work response
            _llm_response("Derived acceptance criteria: test_foo must pass"),
            # Gate check: YES
            _llm_response("YES — criteria are falsifiable and complete"),
        )
        strategy = MasonStrategy()
        identity = _make_identity(phases=[{
            "name": "acceptance_criteria",
            "description": "Derive testable acceptance criteria",
            "exit_gate": "All criteria falsifiable",
            "max_rounds": 3,
        }])
        result = await strategy.reason(
            [{"role": "user", "content": "Implement issue #42"}],
            "test-model",
            llm,
            identity=identity,
        )
        assert result.done
        assert "acceptance_criteria" in result.response
        assert "SATISFIED" in result.response

    async def test_gate_failure_retries(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            # Round 1: work
            _llm_response("First attempt at criteria"),
            # Round 1 gate: NO
            _llm_response("NO — missing error case criteria"),
            # Round 2: more work
            _llm_response("Added error case criteria"),
            # Round 2 gate: YES
            _llm_response("YES — now complete"),
        )
        strategy = MasonStrategy()
        identity = _make_identity(phases=[{
            "name": "acceptance_criteria",
            "description": "Derive criteria",
            "exit_gate": "Cover happy and error cases",
            "max_rounds": 3,
        }])
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
            identity=identity,
        )
        assert "SATISFIED" in result.response

    async def test_max_rounds_advances(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response("Work round 1"),
            _llm_response("NO — not ready"),
            _llm_response("Work round 2"),
            _llm_response("NO — still not ready"),
        )
        strategy = MasonStrategy()
        identity = _make_identity(phases=[{
            "name": "test_phase",
            "description": "Test",
            "exit_gate": "Everything perfect",
            "max_rounds": 2,
        }])
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
            identity=identity,
        )
        assert "MAX_ROUNDS" in result.response

    async def test_multiple_phases_execute_sequentially(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            # Phase 1
            _llm_response("Criteria derived"),
            _llm_response("YES"),
            # Phase 2
            _llm_response("Tests written"),
            _llm_response("YES"),
        )
        strategy = MasonStrategy()
        identity = _make_identity(phases=[
            {"name": "criteria", "exit_gate": "Done", "max_rounds": 2},
            {"name": "tests", "exit_gate": "Done", "max_rounds": 2},
        ])
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
            identity=identity,
        )
        assert "Phase 1: criteria" in result.response
        assert "Phase 2: tests" in result.response
        assert result.response.count("SATISFIED") == 2


class TestToolExecution:
    """Tool calls within phases."""

    async def test_tool_calls_recorded(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            # Round 1: tool call
            _tool_call_response("run_pytest", {"path": "tests/"}),
            # After tool: text response
            _llm_response("Tests pass"),
            # Gate: YES
            _llm_response("YES"),
        )

        tool_calls: list[str] = []

        async def fake_executor(name: str, args: dict[str, Any]) -> str:
            tool_calls.append(name)
            return '{"passed": true}'

        strategy = MasonStrategy()
        identity = _make_identity(phases=[{
            "name": "impl",
            "exit_gate": "Tests green",
            "max_rounds": 2,
        }])
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
            identity=identity,
            tool_executor=fake_executor,
        )
        assert "run_pytest" in tool_calls
        assert len(result.tool_history) >= 1
        assert result.tool_history[0]["tool_name"] == "run_pytest"


class TestGateCheck:
    """Exit gate evaluation."""

    async def test_yes_response_satisfies(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_llm_response("YES — all criteria met"))
        strategy = MasonStrategy()
        result = await strategy._check_exit_gate(
            "test_phase", "All done", "work summary", "model", llm,
        )
        assert result is True

    async def test_no_response_fails(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_llm_response("NO — missing edge cases"))
        strategy = MasonStrategy()
        result = await strategy._check_exit_gate(
            "test_phase", "Cover edge cases", "partial work", "model", llm,
        )
        assert result is False

    async def test_lowercase_yes_works(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_llm_response("yes, the gate is satisfied"))
        strategy = MasonStrategy()
        result = await strategy._check_exit_gate(
            "test_phase", "gate", "work", "model", llm,
        )
        assert result is True


class TestPhaseNoGate:
    """Phases without exit gates always advance."""

    async def test_no_gate_completes_immediately(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response("Did the work"),
        )
        strategy = MasonStrategy()
        identity = _make_identity(phases=[{
            "name": "simple",
            "description": "Just do it",
            "max_rounds": 1,
        }])
        result = await strategy.reason(
            [{"role": "user", "content": "test"}],
            "test-model",
            llm,
            identity=identity,
        )
        assert result.done
