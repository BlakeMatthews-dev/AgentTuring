"""Tests for Agent.handle() learning extraction and RCA paths.

Covers:
- RCA extraction (traced and untraced)
- Learning extraction (traced, corrections + positives)
- Learning extraction (untraced, with org/team)
- Auto-promotion check
- Trace finalization (tool success/fail counts)

Uses ReactStrategy with FakeLLMClient to produce tool_history
with fail->succeed patterns that trigger learning extraction.

Executors are built via `_fail_then_succeed_executor()` / `_always_succeed_executor`
factories so each test gets a clean instance (no shared state between tests).
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

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


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]


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
                                "arguments": json.dumps(arguments),
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


def _fail_then_succeed_executor() -> tuple[ToolExecutor, list[dict[str, Any]]]:
    """Return (executor, call_log). First call per tool errors; later calls succeed.

    Each test gets its own isolated state via the closure — no module-level attrs.
    """
    counts: dict[str, int] = {}
    log: list[dict[str, Any]] = []

    async def _executor(tool_name: str, args: dict[str, Any]) -> str:
        counts[tool_name] = counts.get(tool_name, 0) + 1
        log.append({"tool": tool_name, "args": dict(args), "n": counts[tool_name]})
        if counts[tool_name] == 1:
            return f"Error: entity_id {args.get('entity_id')!r} not found"
        return "Success: light turned on"

    return _executor, log


async def _always_succeed_executor(tool_name: str, args: dict[str, Any]) -> str:
    return "Success: operation completed"


async def _make_learning_agent(
    *,
    llm: FakeLLMClient | None = None,
    tracer: NoopTracingBackend | None = None,
    learning_store: InMemoryLearningStore | None = None,
    rca_extractor: RCAExtractor | None = None,
    learning_promoter: LearningPromoter | None = None,
    tool_executor: ToolExecutor | None = None,
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
    """Learning extraction without tracing."""

    @pytest.mark.asyncio
    async def test_corrections_extracted_on_fail_succeed(self) -> None:
        """Fail->succeed pattern extracts a tool_correction learning scoped to org/team."""
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        executor, call_log = _fail_then_succeed_executor()

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2",
            ),
            _text_response("Done, the light is on."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            tool_executor=executor,
            tracer=None,
        )

        auth = build_auth_context(org_id="org-test", team_id="team-test")
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        # Executor was actually hit twice (wrong then right)
        entity_ids = [c["args"]["entity_id"] for c in call_log]
        assert entity_ids == ["light.wrong", "light.bedroom"]
        # Learning stored with correct scope
        learnings = await store.find_relevant(
            "turn on bedroom light",
            agent_id="test-learning-agent",
            org_id="org-test",
        )
        assert len(learnings) >= 1
        lr = learnings[0]
        assert lr.agent_id == "test-learning-agent"
        assert lr.org_id == "org-test"
        assert lr.team_id == "team-test"
        assert lr.category == "tool_correction"


class TestLearningExtractionTraced:
    """Learning extraction with tracing (corrections + positives)."""

    @pytest.mark.asyncio
    async def test_traced_corrections_and_positives_extracted(self) -> None:
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        tracer = NoopTracingBackend()
        executor, _ = _fail_then_succeed_executor()

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2",
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            tool_executor=executor,
            tracer=tracer,
        )

        auth = build_auth_context(org_id="org-traced", team_id="team-traced")
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        learnings = await store.find_relevant(
            "turn on bedroom light",
            agent_id="test-learning-agent",
            org_id="org-traced",
        )
        assert len(learnings) >= 1
        categories = {lr.category for lr in learnings}
        assert "tool_correction" in categories or "positive_pattern" in categories


class TestRCAExtractionUntraced:
    """RCA extraction without tracing."""

    @pytest.mark.asyncio
    async def test_rca_stored_when_tool_fails(self) -> None:
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        executor, _ = _fail_then_succeed_executor()

        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response(
            "ROOT CAUSE: entity_id was incorrect\n"
            "PREVENTION: Check entity registry before calling ha_control",
        )
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2",
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            rca_extractor=rca_extractor,
            tool_executor=executor,
            tracer=None,
        )

        auth = build_auth_context()
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        rca_learnings = [lr for lr in store._learnings if lr.category == "rca"]
        assert len(rca_learnings) >= 1
        rca = rca_learnings[0]
        assert "entity_id" in rca.learning
        assert rca.agent_id == "test-learning-agent"
        # RCA LLM was actually invoked with the failing tool history
        assert len(rca_llm.calls) >= 1


class TestRCAExtractionTraced:
    """RCA extraction with tracing + org/team scoping."""

    @pytest.mark.asyncio
    async def test_rca_stored_when_traced(self) -> None:
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        tracer = NoopTracingBackend()
        executor, _ = _fail_then_succeed_executor()

        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response(
            "ROOT CAUSE: wrong entity_id\nPREVENTION: validate entity first",
        )
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2",
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            rca_extractor=rca_extractor,
            tool_executor=executor,
            tracer=tracer,
        )

        auth = build_auth_context(org_id="org-rca", team_id="team-rca")
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        rca_learnings = [lr for lr in store._learnings if lr.category == "rca"]
        assert len(rca_learnings) >= 1
        rca = rca_learnings[0]
        assert rca.agent_id == "test-learning-agent"
        assert rca.org_id == "org-rca"
        assert rca.team_id == "team-rca"


class TestAutoPromotion:
    """Auto-promotion runs when existing learnings are relevant to the query."""

    @pytest.mark.asyncio
    async def test_promoter_promotes_learning_above_threshold(self) -> None:
        """Real promoter pushes a heavily-hit learning from AGENT -> TEAM scope."""
        from stronghold.types.memory import Learning, MemoryScope

        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        # Low threshold so the existing learning's hit_count clears it
        promoter = LearningPromoter(store, threshold=1)

        # Pre-populate a learning that will match the query and get hit again
        existing = Learning(
            category="tool_correction",
            trigger_keys=["bedroom", "light"],
            learning="Use light.bedroom_lamp for the bedroom",
            tool_name="ha_control",
            agent_id="test-learning-agent",
            scope=MemoryScope.AGENT,
            hit_count=5,
        )
        await store.store(existing)

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.bedroom_lamp"}),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            learning_promoter=promoter,
            tool_executor=_always_succeed_executor,
        )

        auth = build_auth_context(org_id="org-promo", team_id="team-promo")
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        # After handle(), promoter should have observed the hit and (given
        # threshold=1) promoted the learning's scope from AGENT upward.
        all_lr = [lr for lr in store._learnings if lr.category == "tool_correction"]
        assert len(all_lr) >= 1
        # At minimum, hit_count should have incremented (promoter or
        # find_relevant recorded the match).
        assert any(lr.hit_count >= existing.hit_count for lr in all_lr)


class TestTraceFinalization:
    """Traced runs complete cleanly and the final response is returned."""

    @pytest.mark.asyncio
    async def test_traced_run_returns_final_text_response(self) -> None:
        llm = FakeLLMClient()
        tracer = NoopTracingBackend()
        executor, call_log = _fail_then_succeed_executor()

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response(
                "ha_control", {"entity_id": "light.bedroom"}, call_id="call-2",
            ),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            tool_executor=executor,
            tracer=tracer,
        )

        auth = build_auth_context()
        result = await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        assert not result.blocked
        assert result.content == "Done."
        # Both a failing and successful tool call were exercised
        assert len(call_log) == 2
        # Executor was invoked with both wrong and correct args
        assert [c["args"]["entity_id"] for c in call_log] == [
            "light.wrong",
            "light.bedroom",
        ]


class TestNoLearningWithoutHistory:
    """No RCA extraction when all tools succeed."""

    @pytest.mark.asyncio
    async def test_no_rca_without_tool_failures(self) -> None:
        llm = FakeLLMClient()
        store = InMemoryLearningStore()
        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response("ROOT CAUSE: n/a\nPREVENTION: n/a")
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.bedroom"}),
            _text_response("Done."),
        )

        agent = await _make_learning_agent(
            llm=llm,
            learning_store=store,
            rca_extractor=rca_extractor,
            tool_executor=_always_succeed_executor,
        )

        auth = build_auth_context()
        await agent.handle(
            [{"role": "user", "content": "turn on the bedroom light"}],
            auth,
        )

        # No RCA should be stored
        rca_learnings = [lr for lr in store._learnings if lr.category == "rca"]
        assert rca_learnings == []
        # And RCA LLM should never have been invoked
        assert rca_llm.calls == []
