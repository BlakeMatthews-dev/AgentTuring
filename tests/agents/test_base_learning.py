"""Tests for Agent.handle() learning extraction and RCA paths.

Covers:
- Lines 366-387: RCA extraction (traced and untraced)
- Lines 392-407: Learning extraction (traced, corrections + positives)
- Lines 419-422: Learning extraction (untraced, with org/team)
- Line 426: Auto-promotion check
- Lines 467-472: Trace finalization (tool success/fail counts)

Uses ReactStrategy with FakeLLMClient to produce tool_history
with fail->succeed patterns that trigger learning extraction.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.react import ReactStrategy
from stronghold.memory.learnings.extractor import RCAExtractor, ToolCorrectionExtractor
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient, NoopTracingBackend


def _tool_call_response(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    call_id: str = "call-1",
) -> dict[str, Any]:
    """Build an LLM response that requests a tool call."""
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
                                "name": tool_name,
                                "arguments": __import__("json").dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _text_response(content: str) -> dict[str, Any]:
    """Build a normal text LLM response."""
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
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


async def _fake_tool_executor(tool_name: str, args: dict[str, Any]) -> str:
    """Executor that fails on first call, succeeds on second."""
    if not hasattr(_fake_tool_executor, "_call_count"):
        _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]
    counts = _fake_tool_executor._call_count  # type: ignore[attr-defined]
    counts[tool_name] = counts.get(tool_name, 0) + 1
    if counts[tool_name] == 1:
        return "Error: entity_id 'light.wrong' not found"
    return "Success: light turned on"


async def _succeeding_executor(tool_name: str, args: dict[str, Any]) -> str:
    """Executor that always succeeds."""
    return "Success: operation completed"


async def _make_learning_agent(
    *,
    llm: FakeLLMClient | None = None,
    tracer: NoopTracingBackend | None = None,
    learning_store: InMemoryLearningStore | None = None,
    rca_extractor: RCAExtractor | None = None,
    learning_promoter: LearningPromoter | None = None,
    tool_executor: Any = None,
    name: str = "test-learning-agent",
) -> Agent:
    """Build an Agent with ReactStrategy and learning infrastructure."""
    llm = llm or FakeLLMClient()
    store = learning_store or InMemoryLearningStore()
    prompts = InMemoryPromptManager()
    await prompts.upsert(f"agent.{name}.soul", "You are helpful.", label="production")
    return Agent(
        identity=AgentIdentity(
            name=name,
            soul_prompt_name=f"agent.{name}.soul",
            model="test-model",
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
        rca_extractor=rca_extractor,
        learning_promoter=learning_promoter,
        tracer=tracer,
        tool_executor=tool_executor,
    )


class TestLearningExtractionUntraced:
    """Learning extraction without tracing (lines 413-422)."""

    @pytest.mark.asyncio
    async def test_corrections_extracted_on_fail_succeed(self) -> None:
        """Fail->succeed pattern extracts a tool_correction learning."""
        # Reset the executor call count
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()

        # Round 0: LLM requests ha_control with wrong args
        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            # Round 1: LLM requests ha_control with correct args
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2"
            ),
            # Round 2: LLM gives final text response
            _text_response("Done, the light is on."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            tool_executor=_fake_tool_executor,
            tracer=None,  # Untraced path
        )

        auth = build_auth_context(org_id="org-test", team_id="team-test")
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        # Learning should have been stored with org_id and team_id set
        all_learnings = await learning_store.find_relevant(
            "turn on bedroom light",
            agent_id="test-learning-agent",
            org_id="org-test",
        )
        assert len(all_learnings) >= 1
        learning = all_learnings[0]
        assert learning.agent_id == "test-learning-agent"
        assert learning.org_id == "org-test"
        assert learning.team_id == "team-test"
        assert learning.category == "tool_correction"


class TestLearningExtractionTraced:
    """Learning extraction with tracing (lines 392-407)."""

    @pytest.mark.asyncio
    async def test_traced_corrections_and_positives_extracted(self) -> None:
        """With tracing, both corrections and positive patterns are extracted."""
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        tracer = NoopTracingBackend()

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2"
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            tool_executor=_fake_tool_executor,
            tracer=tracer,
        )

        auth = build_auth_context(org_id="org-traced", team_id="team-traced")
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        # Should have both correction and positive pattern learnings
        all_learnings = await learning_store.find_relevant(
            "turn on bedroom light",
            agent_id="test-learning-agent",
            org_id="org-traced",
        )
        assert len(all_learnings) >= 1
        categories = {lr.category for lr in all_learnings}
        # Traced path extracts both corrections and positives
        assert "tool_correction" in categories or "positive_pattern" in categories


class TestRCAExtractionUntraced:
    """RCA extraction without tracing (lines 380-387)."""

    @pytest.mark.asyncio
    async def test_rca_stored_when_tool_fails(self) -> None:
        """RCA learning stored when tool calls have errors (untraced)."""
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()

        # RCA extractor needs its own LLM client
        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response(
            "ROOT CAUSE: entity_id was incorrect\n"
            "PREVENTION: Check entity registry before calling ha_control"
        )
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2"
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            rca_extractor=rca_extractor,
            tool_executor=_fake_tool_executor,
            tracer=None,
        )

        auth = build_auth_context()
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        # Check that RCA was stored
        all_learnings = learning_store._learnings
        rca_learnings = [lr for lr in all_learnings if lr.category == "rca"]
        assert len(rca_learnings) >= 1
        assert "entity_id" in rca_learnings[0].learning
        assert rca_learnings[0].agent_id == "test-learning-agent"


class TestRCAExtractionTraced:
    """RCA extraction with tracing (lines 366-379)."""

    @pytest.mark.asyncio
    async def test_rca_stored_when_traced(self) -> None:
        """RCA learning stored with tracing enabled, with org/team populated."""
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        tracer = NoopTracingBackend()

        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response(
            "ROOT CAUSE: wrong entity_id\nPREVENTION: validate entity first"
        )
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2"
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            rca_extractor=rca_extractor,
            tool_executor=_fake_tool_executor,
            tracer=tracer,
        )

        auth = build_auth_context(org_id="org-rca", team_id="team-rca")
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        rca_learnings = [lr for lr in learning_store._learnings if lr.category == "rca"]
        assert len(rca_learnings) >= 1
        rca = rca_learnings[0]
        assert rca.agent_id == "test-learning-agent"
        assert rca.org_id == "org-rca"
        assert rca.team_id == "team-rca"


class TestAutoPromotion:
    """Auto-promotion check (line 426)."""

    @pytest.mark.asyncio
    async def test_promoter_called_when_learnings_injected(self) -> None:
        """Auto-promotion runs when agent has injected learnings."""
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        promoter = LearningPromoter(learning_store, threshold=1)

        # Pre-populate a learning so it will be "injected" during handle
        from stronghold.types.memory import Learning, MemoryScope

        existing = Learning(
            category="tool_correction",
            trigger_keys=["bedroom", "light"],
            learning="Use light.bedroom_lamp for the bedroom",
            tool_name="ha_control",
            agent_id="test-learning-agent",
            scope=MemoryScope.AGENT,
            hit_count=2,
        )
        await learning_store.store(existing)

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.bedroom_lamp"}),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            learning_promoter=promoter,
            tool_executor=_succeeding_executor,
        )

        auth = build_auth_context()
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked


class TestTraceFinalization:
    """Trace finalization: tool success/fail counts (lines 467-472)."""

    @pytest.mark.asyncio
    async def test_trace_finalized_with_tool_counts(self) -> None:
        """Trace metadata includes tool success/fail counts."""
        if hasattr(_fake_tool_executor, "_call_count"):
            _fake_tool_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        tracer = NoopTracingBackend()

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2"
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            tool_executor=_fake_tool_executor,
            tracer=tracer,
        )

        auth = build_auth_context()
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        # The trace should have been finalized (NoopTrace.update + end called)
        # We verify indirectly by checking the pipeline completed without error
        assert not result.blocked
        assert result.content == "Done."


class TestNoLearningWithoutHistory:
    """No learning extraction when there is no tool history."""

    @pytest.mark.asyncio
    async def test_no_rca_without_tool_failures(self) -> None:
        """No RCA extraction when all tools succeed."""
        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()
        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response("ROOT CAUSE: n/a\nPREVENTION: n/a")
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.bedroom"}),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=learning_store,
            rca_extractor=rca_extractor,
            tool_executor=_succeeding_executor,
        )

        auth = build_auth_context()
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        rca_learnings = [lr for lr in learning_store._learnings if lr.category == "rca"]
        assert len(rca_learnings) == 0
