"""Test the Artificer's plan-execute workflow.

The Artificer should:
1. Plan: decompose task into phases
2. For each phase: write tests → write code → run checks → commit
3. Only proceed to next phase when current passes
"""

import pytest

from tests.fakes import FakeLLMClient


class TestArtificerPlanExecute:
    @pytest.mark.asyncio
    async def test_planner_decomposes_task(self) -> None:
        """Planner sub-agent should break task into numbered subtasks."""
        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.direct import DirectStrategy
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity
        from tests.factories import build_auth_context

        llm = FakeLLMClient()
        llm.set_simple_response(
            "## Plan\n"
            "1. Create src/stronghold/utils.py with is_palindrome function\n"
            "2. Create tests/test_palindrome.py with pytest tests\n"
            "3. Run ruff check and mypy\n"
            "4. Commit changes"
        )
        prompts = InMemoryPromptManager()
        await prompts.upsert(
            "agent.planner.soul",
            "Decompose tasks into numbered phases. Each phase should be testable.",
            label="production",
        )
        planner = Agent(
            identity=AgentIdentity(
                name="planner",
                soul_prompt_name="agent.planner.soul",
                model="m",
                memory_config={},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )
        result = await planner.handle(
            [{"role": "user", "content": "Create a palindrome checker with tests"}],
            build_auth_context(),
        )
        assert "1." in result.content
        assert "2." in result.content

    @pytest.mark.asyncio
    async def test_reviewer_runs_all_checks(self) -> None:
        """Reviewer should call all quality tools and report pass/fail."""
        tool_calls: list[str] = []

        async def mock_tool(name: str, args: dict) -> str:
            tool_calls.append(name)
            return "PASSED: All checks passed"

        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.react import ReactStrategy
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity
        from tests.factories import build_auth_context

        llm = FakeLLMClient()
        # LLM returns tool calls for each quality check
        llm.set_responses(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "function": {
                                        "name": "run_pytest",
                                        "arguments": '{"path":"tests/"}',
                                    },
                                },
                                {
                                    "id": "t2",
                                    "function": {
                                        "name": "run_ruff_check",
                                        "arguments": '{"path":"src/"}',
                                    },
                                },
                                {
                                    "id": "t3",
                                    "function": {
                                        "name": "run_mypy",
                                        "arguments": '{"path":"src/"}',
                                    },
                                },
                                {
                                    "id": "t4",
                                    "function": {
                                        "name": "run_bandit",
                                        "arguments": '{"path":"src/"}',
                                    },
                                },
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "All 4 checks passed. APPROVED."}}
                ]
            },
        )
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.reviewer.soul", "Run all quality checks.", label="production")

        reviewer = Agent(
            identity=AgentIdentity(
                name="reviewer",
                soul_prompt_name="agent.reviewer.soul",
                model="m",
                tools=("run_pytest", "run_ruff_check", "run_mypy", "run_bandit"),
                memory_config={},
            ),
            strategy=ReactStrategy(max_rounds=2),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            tool_executor=mock_tool,
        )

        result = await reviewer.handle(
            [{"role": "user", "content": "Review the code changes"}],
            build_auth_context(),
        )
        assert "APPROVED" in result.content
        assert "run_pytest" in tool_calls
        assert "run_ruff_check" in tool_calls
        assert "run_mypy" in tool_calls
        assert "run_bandit" in tool_calls
