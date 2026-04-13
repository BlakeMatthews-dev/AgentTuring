"""Tests for InMemoryAgentStore dynamic agent dependency wiring.

Covers:
- C15: Dynamic agents must receive ALL dependencies from the reference agent,
  not just a subset (was only 4 of 14+ deps).
"""

from __future__ import annotations

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from tests.fakes import (
    FakeLLMClient,
    FakeQuotaTracker,
    NoopTracingBackend,
)


def _make_fully_wired_agent(name: str = "reference") -> Agent:
    """Build an agent with ALL dependencies populated for reference cloning."""
    llm = FakeLLMClient()
    prompts = InMemoryPromptManager()
    warden = Warden()
    learning_store = InMemoryLearningStore()
    learning_extractor = ToolCorrectionExtractor()
    learning_promoter = LearningPromoter(learning_store, threshold=5)
    session_store = InMemorySessionStore()
    outcome_store = InMemoryOutcomeStore()
    quota_tracker = FakeQuotaTracker()
    tracer = NoopTracingBackend()
    audit_log = InMemoryAuditLog()
    sentinel = Sentinel(
        warden=warden,
        permission_table=PermissionTable.from_config({"admin": ["*"]}),
        audit_log=audit_log,
    )

    return Agent(
        identity=AgentIdentity(name=name, tools=("web_search",)),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=ContextBuilder(),
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        rca_extractor=None,
        learning_promoter=learning_promoter,
        sentinel=sentinel,
        outcome_store=outcome_store,
        session_store=session_store,
        quota_tracker=quota_tracker,
        coin_ledger=None,
        tracer=tracer,
        tool_executor=None,
    )


class TestDynamicAgentDependencyCopying:
    """C15: InMemoryAgentStore.create() must copy ALL deps from ref agent."""

    async def test_new_agent_gets_all_deps_from_reference(self) -> None:
        """A dynamically created agent gets every dep the reference has."""
        ref_agent = _make_fully_wired_agent()
        store = InMemoryAgentStore(
            {"reference": ref_agent},
            prompt_manager=InMemoryPromptManager(),
        )

        identity = AgentIdentity(
            name="dynamic-agent",
            reasoning_strategy="direct",
        )
        await store.create(identity, "Dynamic soul.", "")

        created = store._agents["dynamic-agent"]

        # All deps that the reference had must be propagated
        assert created._llm is ref_agent._llm
        assert created._context_builder is ref_agent._context_builder
        assert created._prompt_manager is ref_agent._prompt_manager
        assert created._warden is ref_agent._warden
        assert created._learning_store is ref_agent._learning_store
        assert created._learning_extractor is ref_agent._learning_extractor
        assert created._learning_promoter is ref_agent._learning_promoter
        assert created._sentinel is ref_agent._sentinel
        assert created._outcome_store is ref_agent._outcome_store
        assert created._session_store is ref_agent._session_store
        assert created._quota_tracker is ref_agent._quota_tracker
        assert created._tracer is ref_agent._tracer

    async def test_new_agent_gets_coin_ledger_from_reference(self) -> None:
        """coin_ledger must be copied even though it is often None."""
        ref_agent = _make_fully_wired_agent()
        # Simulate a coin_ledger being set
        ref_agent._coin_ledger = object()  # type: ignore[assignment]

        store = InMemoryAgentStore(
            {"reference": ref_agent},
            prompt_manager=InMemoryPromptManager(),
        )

        identity = AgentIdentity(
            name="coin-test",
            reasoning_strategy="direct",
        )
        await store.create(identity, "Soul.", "")

        created = store._agents["coin-test"]
        assert created._coin_ledger is ref_agent._coin_ledger

    async def test_new_agent_gets_rca_extractor_from_reference(self) -> None:
        """rca_extractor must be copied from reference."""
        ref_agent = _make_fully_wired_agent()
        # Simulate rca_extractor being set
        ref_agent._rca_extractor = object()  # type: ignore[assignment]

        store = InMemoryAgentStore(
            {"reference": ref_agent},
            prompt_manager=InMemoryPromptManager(),
        )

        identity = AgentIdentity(
            name="rca-test",
            reasoning_strategy="direct",
        )
        await store.create(identity, "Soul.", "")

        created = store._agents["rca-test"]
        assert created._rca_extractor is ref_agent._rca_extractor

    async def test_new_agent_gets_tool_executor_from_reference(self) -> None:
        """tool_executor must be copied from reference."""
        ref_agent = _make_fully_wired_agent()
        ref_agent._tool_executor = object()  # type: ignore[assignment]

        store = InMemoryAgentStore(
            {"reference": ref_agent},
            prompt_manager=InMemoryPromptManager(),
        )

        identity = AgentIdentity(
            name="tool-test",
            reasoning_strategy="direct",
            tools=("web_search",),
        )
        await store.create(identity, "Soul.", "")

        created = store._agents["tool-test"]
        assert created._tool_executor is ref_agent._tool_executor


class TestOrgIsolationInGet:
    """Agent store org_id isolation check."""

    async def test_org_scoped_get_hides_other_org_agents(self) -> None:
        """get() with org_id filters out agents from other orgs."""
        agent = _make_fully_wired_agent()
        # Override identity to have an org_id
        agent_with_org = Agent(
            identity=AgentIdentity(name="org-agent", org_id="org-alpha"),
            strategy=DirectStrategy(),
            llm=agent._llm,
            context_builder=agent._context_builder,
            prompt_manager=agent._prompt_manager,
            warden=agent._warden,
        )
        store = InMemoryAgentStore(
            {"org-agent": agent_with_org},
            prompt_manager=InMemoryPromptManager(),
        )

        # Same org can see it
        result = await store.get("org-agent", org_id="org-alpha")
        assert result is not None

        # Different org cannot see it
        result = await store.get("org-agent", org_id="org-beta")
        assert result is None

    async def test_global_agent_visible_to_all_orgs(self) -> None:
        """Agents with empty org_id are visible to all."""
        agent = _make_fully_wired_agent()
        store = InMemoryAgentStore(
            {"reference": agent},
            prompt_manager=InMemoryPromptManager(),
        )

        result = await store.get("reference", org_id="any-org")
        assert result is not None
