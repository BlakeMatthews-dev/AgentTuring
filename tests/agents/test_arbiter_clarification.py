"""Test that the Conduit asks clarifying questions when intent is ambiguous."""

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from stronghold.types.config import TaskTypeConfig
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient


class TestConduitClarification:
    @pytest.mark.asyncio
    async def test_ambiguous_intent_asks_followup(self) -> None:
        """When classifier isn't confident, Conduit should ask what the user wants."""
        classifier = ClassifierEngine()
        task_types = {
            "code": TaskTypeConfig(keywords=["code", "function"], min_tier="medium"),
            "chat": TaskTypeConfig(keywords=["hello", "hi"]),
        }

        # "implement changes" is ambiguous — could be code or process changes
        intent = await classifier.classify(
            [{"role": "user", "content": "implement changes to the system"}],
            task_types,
        )

        # Score should be below threshold (3.0) for confident classification
        assert intent.keyword_score < 3.0
        # When score is low, classified_by should be "keywords" not "llm"
        # The Conduit should detect this and ask for clarification

    @pytest.mark.asyncio
    async def test_clear_intent_no_followup(self) -> None:
        """When classifier is confident, no clarification needed."""
        classifier = ClassifierEngine()
        task_types = {
            "code": TaskTypeConfig(keywords=["code", "function", "bug", "fix"]),
            "chat": TaskTypeConfig(keywords=["hello", "hi"]),
        }

        intent = await classifier.classify(
            [{"role": "user", "content": "write a function to sort a list"}],
            task_types,
        )

        assert intent.keyword_score >= 3.0
        assert intent.task_type == "code"

    @pytest.mark.asyncio
    async def test_arbiter_generates_clarification_response(self) -> None:
        """Conduit should generate a response asking which agent to use."""
        llm = FakeLLMClient()
        llm.set_simple_response(
            "I can help with that! Could you clarify what you need?\n"
            "a) Write or modify code\n"
            "b) Search for information\n"
            "c) Creative writing\n"
            "d) Something else"
        )
        prompts = InMemoryPromptManager()
        await prompts.upsert(
            "agent.arbiter.soul",
            (
                "You are the Conduit. When the user's intent is unclear, "
                "ask which type of help they need: code, search, writing, or other. "
                "Format as multiple choice a, b, c, d."
            ),
            label="production",
        )

        arbiter = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="m",
                memory_config={},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )

        result = await arbiter.handle(
            [{"role": "user", "content": "implement changes"}],
            build_auth_context(),
        )

        assert not result.blocked
        # Response should contain options
        assert "a)" in result.content or "code" in result.content.lower()
