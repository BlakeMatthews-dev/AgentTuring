"""Test that tool schemas are injected into LLM calls for tool-capable agents."""

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


class TestToolSchemaInjection:
    @pytest.mark.asyncio
    async def test_llm_receives_tool_definitions(self) -> None:
        """Agent with tools should pass OpenAI tool schemas to the LLM."""
        llm = FakeLLMClient()
        llm.set_simple_response("I'll run the tests for you.")
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "Test agent.", label="production")

        agent = Agent(
            identity=AgentIdentity(
                name="test",
                soul_prompt_name="agent.test.soul",
                model="m",
                tools=("run_pytest", "run_ruff_check"),
                memory_config={},
            ),
            strategy=ReactStrategy(max_rounds=1),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )

        await agent.handle(
            [{"role": "user", "content": "run the tests"}],
            build_auth_context(),
        )

        # Verify tools were passed to LLM
        assert len(llm.calls) >= 1
        call = llm.calls[0]
        assert "tools" in call
        assert call["tools"] is not None
        tool_names = [t["function"]["name"] for t in call["tools"]]
        assert "run_pytest" in tool_names
        assert "run_ruff_check" in tool_names

    @pytest.mark.asyncio
    async def test_agent_without_tools_no_injection(self) -> None:
        """Agent without tools should NOT pass tool definitions to LLM."""
        llm = FakeLLMClient()
        llm.set_simple_response("Hello!")
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "Test.", label="production")

        agent = Agent(
            identity=AgentIdentity(
                name="test",
                soul_prompt_name="agent.test.soul",
                model="m",
                tools=(),
                memory_config={},
            ),
            strategy=ReactStrategy(max_rounds=1),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )

        await agent.handle(
            [{"role": "user", "content": "hello"}],
            build_auth_context(),
        )

        call = llm.calls[0]
        tools = call.get("tools")
        assert tools is None or tools == []
