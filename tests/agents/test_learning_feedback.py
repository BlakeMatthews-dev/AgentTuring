"""Tests for learning extraction after tool loops.

Three layers, each verifying real behavior end-to-end:

  1. Extractor: fail->succeed tool history produces a `tool_correction`
     (and an all-success history produces none).
  2. Store round-trip: extracted learnings are retrievable by trigger query.
  3. Full Agent pipeline: ReactStrategy + Agent.handle() actually invokes
     the tool executor with both wrong + right args and persists the
     extracted learning.
"""

from __future__ import annotations

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.react import ReactStrategy
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient


def _tool_call_response(entity_id: str, *, call_id: str = "tc1") -> dict:
    """LLM response requesting an ha_control tool call."""
    return {
        "id": "chatcmpl-tool",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "ha_control",
                                "arguments": f'{{"entity_id": "{entity_id}"}}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _text_response(content: str) -> dict:
    return {
        "id": "chatcmpl-text",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


class TestToolCorrectionExtractor:
    """Direct extractor behavior - fail->succeed produces a correction."""

    def test_extract_corrections_from_fail_succeed_pair(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.wrong"},
                "result": "Error: not found",
                "round": 0,
            },
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 1,
            },
        ]
        corrections = extractor.extract_corrections("turn on the fan", tool_history)

        assert len(corrections) >= 1
        correction = corrections[0]
        assert correction.tool_name == "ha_control"
        assert correction.category == "tool_correction"

    def test_extract_no_corrections_from_all_success(self) -> None:
        extractor = ToolCorrectionExtractor()
        tool_history = [
            {
                "tool_name": "ha_control",
                "arguments": {"entity_id": "fan.bedroom"},
                "result": "OK",
                "round": 0,
            },
        ]
        assert extractor.extract_corrections("turn on the fan", tool_history) == []


class TestLearningStorageRoundTrip:
    """Extracted corrections survive store+retrieve on InMemoryLearningStore."""

    @pytest.mark.asyncio
    async def test_correction_is_retrievable_by_trigger_query(self) -> None:
        extractor = ToolCorrectionExtractor()
        store = InMemoryLearningStore()
        tool_history = [
            {"tool_name": "ha_control", "arguments": {"entity_id": "fan.wrong"},
             "result": "Error: not found", "round": 0},
            {"tool_name": "ha_control", "arguments": {"entity_id": "fan.bedroom"},
             "result": "OK", "round": 1},
        ]

        for c in extractor.extract_corrections("turn on the fan", tool_history):
            c.agent_id = "test-agent"
            await store.store(c)

        retrieved = await store.find_relevant("turn on the fan", agent_id="test-agent")
        assert len(retrieved) >= 1
        assert retrieved[0].agent_id == "test-agent"
        assert retrieved[0].category == "tool_correction"


class TestLearningFeedbackEndToEnd:
    """Full pipeline: ReactStrategy+Agent with tool failure extracts a learning."""

    @pytest.mark.asyncio
    async def test_fail_succeed_loop_extracts_learning_through_agent(self) -> None:
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test.soul", "You are helpful.", label="production")

        llm.set_responses(
            _tool_call_response("fan.wrong"),
            _tool_call_response("fan.bedroom", call_id="tc2"),
            _text_response("Turned on the fan."),
        )

        tool_calls: list[tuple[str, dict]] = []

        async def tool_executor(name: str, args: dict) -> str:
            tool_calls.append((name, args))
            if args.get("entity_id") == "fan.wrong":
                return "Error: entity_id 'fan.wrong' not found"
            return "OK"

        agent = Agent(
            identity=AgentIdentity(
                name="test",
                soul_prompt_name="agent.test.soul",
                model="m",
                tools=("ha_control",),
                memory_config={"learnings": True},
            ),
            strategy=ReactStrategy(max_rounds=3),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=store,
            learning_extractor=ToolCorrectionExtractor(),
            tool_executor=tool_executor,
        )

        auth = build_auth_context()
        result = await agent.handle(
            [{"role": "user", "content": "turn on the fan"}],
            auth,
        )

        assert not result.blocked
        # Agent actually invoked the executor with both wrong and right args
        entity_ids = [args.get("entity_id") for _, args in tool_calls]
        assert "fan.wrong" in entity_ids
        assert "fan.bedroom" in entity_ids
        # And a correction learning was extracted and persisted
        retrieved = await store.find_relevant("turn on the fan", agent_id="test")
        assert any(lr.category == "tool_correction" for lr in retrieved)
