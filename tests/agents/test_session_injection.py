"""Tests for session history injection."""

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.agent import AgentIdentity
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient


class TestSessionInjection:
    @pytest.mark.asyncio
    async def test_session_history_prepended(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("I remember!")
        session_store = InMemorySessionStore()
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are helpful.", label="production")

        agent = Agent(
            identity=AgentIdentity(name="test", soul_prompt_name="agent.test.soul", model="m"),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            session_store=session_store,
        )
        auth = build_auth_context()

        # First request — creates session
        await agent.handle(
            [{"role": "user", "content": "my name is Blake"}],
            auth,
            session_id="s1",
        )

        # Second request — should include history
        llm.set_simple_response("Yes, your name is Blake!")
        await agent.handle(
            [{"role": "user", "content": "what is my name?"}],
            auth,
            session_id="s1",
        )

        # The second LLM call should have history prepended
        second_call = llm.calls[-1]
        messages = second_call["messages"]
        # Should contain: system + history (user + assistant) + new user
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) >= 2  # history user + new user
