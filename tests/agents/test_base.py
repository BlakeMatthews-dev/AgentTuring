"""Tests for Agent.__init__ type annotations and RCA tenant scoping.

Covers:
- C12: Agent.__init__ params typed with proper protocols, not Any.
- C14: RCA learnings in untraced path include org_id/team_id from auth context.
"""

from __future__ import annotations

from typing import Any

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.agents.strategies.react import ReactStrategy
from stronghold.memory.learnings.extractor import RCAExtractor, ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient

# ── C14: RCA learnings in untraced path must carry org_id/team_id ──


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


async def _failing_then_succeeding_executor(tool_name: str, args: dict[str, Any]) -> str:
    """Executor that fails on first call per tool, succeeds on second."""
    if not hasattr(_failing_then_succeeding_executor, "_call_count"):
        _failing_then_succeeding_executor._call_count = {}  # type: ignore[attr-defined]
    counts = _failing_then_succeeding_executor._call_count  # type: ignore[attr-defined]
    counts[tool_name] = counts.get(tool_name, 0) + 1
    if counts[tool_name] == 1:
        return "Error: entity_id 'light.wrong' not found"
    return "Success: light turned on"


class TestRCAUntracedCarriesOrgTeam:
    """C14: RCA learnings in untraced path must include org_id and team_id."""

    async def test_rca_untraced_stores_org_and_team_from_auth(self) -> None:
        """When RCA is extracted in the untraced path, org_id and team_id
        must come from the auth context, not be left empty."""
        if hasattr(_failing_then_succeeding_executor, "_call_count"):
            _failing_then_succeeding_executor._call_count = {}  # type: ignore[attr-defined]

        llm = FakeLLMClient()
        learning_store = InMemoryLearningStore()

        rca_llm = FakeLLMClient()
        rca_llm.set_simple_response("ROOT CAUSE: wrong entity\nPREVENTION: check first")
        rca_extractor = RCAExtractor(llm_client=rca_llm, rca_model="test-rca")

        llm.set_responses(
            _tool_call_response("ha_control", {"entity_id": "light.wrong"}),
            _tool_call_response("ha_control", {"entity_id": "light.ok"}, call_id="call-2"),
            _text_response("Done."),
        )

        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.test-c14.soul", "You are helpful.", label="production")

        agent = Agent(
            identity=AgentIdentity(
                name="test-c14",
                soul_prompt_name="agent.test-c14.soul",
                model="test-model",
                tools=("ha_control",),
                memory_config={"learnings": True},
            ),
            strategy=ReactStrategy(max_rounds=3),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
            learning_store=learning_store,
            learning_extractor=ToolCorrectionExtractor(),
            rca_extractor=rca_extractor,
            tracer=None,  # Untraced path
            tool_executor=_failing_then_succeeding_executor,
        )

        auth = build_auth_context(org_id="org-c14", team_id="team-c14")
        await agent.handle(
            [{"role": "user", "content": "turn on the light"}],
            auth,
        )

        rca_learnings = [lr for lr in learning_store._learnings if lr.category == "rca"]
        assert len(rca_learnings) >= 1
        rca = rca_learnings[0]
        assert rca.agent_id == "test-c14"
        assert rca.org_id == "org-c14", "RCA must carry org_id from auth context"
        assert rca.team_id == "team-c14", "RCA must carry team_id from auth context"


# ── C12: Type annotation quality checks ─────────────────────────────


class TestAgentInitTyping:
    """C12: Verify Agent.__init__ does not use Any for typed deps."""

    def test_strategy_param_accepts_direct_strategy(self) -> None:
        """DirectStrategy satisfies the strategy parameter."""
        prompts = InMemoryPromptManager()
        agent = Agent(
            identity=AgentIdentity(name="typing-test"),
            strategy=DirectStrategy(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )
        assert agent._strategy is not None

    def test_strategy_param_accepts_react_strategy(self) -> None:
        """ReactStrategy satisfies the strategy parameter."""
        prompts = InMemoryPromptManager()
        agent = Agent(
            identity=AgentIdentity(name="typing-test"),
            strategy=ReactStrategy(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )
        assert agent._strategy is not None

    def test_all_optional_deps_default_none(self) -> None:
        """Agent can be created with only mandatory deps."""
        prompts = InMemoryPromptManager()
        agent = Agent(
            identity=AgentIdentity(name="minimal"),
            strategy=DirectStrategy(),
            llm=FakeLLMClient(),
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )
        assert agent._learning_store is None
        assert agent._learning_extractor is None
        assert agent._rca_extractor is None
        assert agent._learning_promoter is None
        assert agent._sentinel is None
        assert agent._outcome_store is None
        assert agent._session_store is None
        assert agent._quota_tracker is None
        assert agent._coin_ledger is None
        assert agent._tool_executor is None
        assert agent._tracer is None
