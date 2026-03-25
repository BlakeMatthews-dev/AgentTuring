"""Test that Artificer's tool calls actually reach the tool executor.

This test will be RED until we wire tool_executor into Agent.handle() → ReactStrategy.
"""

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.react import ReactStrategy
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient


class TestToolWiring:
    @pytest.mark.asyncio
    async def test_tool_call_reaches_executor(self) -> None:
        """When LLM returns a tool_call, the executor MUST be called."""
        llm = FakeLLMClient()
        tool_calls_received: list[tuple[str, dict]] = []

        async def mock_executor(name: str, args: dict) -> str:
            tool_calls_received.append((name, args))
            return "PASSED: All checks passed"

        llm.set_responses(
            # Round 1: LLM returns tool call
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "function": {
                                        "name": "run_pytest",
                                        "arguments": '{"path": "."}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
            # Round 2: LLM sees result and responds
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Tests pass!"},
                    }
                ],
            },
        )

        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "Test agent.", label="production")

        strategy = ReactStrategy(max_rounds=3)

        agent = Agent(
            identity=AgentIdentity(
                name="test",
                soul_prompt_name="agent.test.soul",
                model="m",
                tools=("run_pytest",),
                memory_config={},
            ),
            strategy=strategy,
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=InMemoryLearningStore(),
            tool_executor=mock_executor,
        )

        result = await agent.handle(
            [{"role": "user", "content": "run tests"}],
            build_auth_context(),
        )

        assert len(tool_calls_received) == 1
        assert tool_calls_received[0][0] == "run_pytest"
        assert result.content == "Tests pass!"
