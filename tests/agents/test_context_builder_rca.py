"""Spec A: ContextBuilder renders rca_category as a tag on promoted learnings."""

from __future__ import annotations

from typing import Any

from stronghold.agents.context_builder import ContextBuilder
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.memory import Learning, MemoryScope


class _StubPromptManager:
    async def get(self, name: str, *, label: str = "active") -> str:
        return "You are a test agent."

    async def get_with_config(
        self, name: str, *, label: str = "active"
    ) -> tuple[str, dict[str, Any]]:
        return "You are a test agent.", {}

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "active",
    ) -> None:
        pass


async def _build_with_store(store: InMemoryLearningStore) -> str:
    identity = AgentIdentity(
        name="test-agent",
        version="1.0",
        description="Test",
        soul_prompt_name="agent.test.soul",
        reasoning_strategy="direct",
        memory_config={"learnings": True},
    )
    builder = ContextBuilder()
    messages = [{"role": "user", "content": "anything"}]
    result_messages, _ = await builder.build(
        messages,
        identity,
        prompt_manager=_StubPromptManager(),
        learning_store=store,
        agent_id="test-agent",
        org_id="org-1",
    )
    system_msg = result_messages[0]
    assert system_msg["role"] == "system"
    content = system_msg["content"]
    return content if isinstance(content, str) else ""


class TestContextBuilderRCATag:
    """Promoted learnings with rca_category are rendered with a [category] tag."""

    async def test_rca_category_renders_as_tag(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(
            Learning(
                category="rca",
                trigger_keys=["fan"],
                learning="CATEGORY: rate_limit\nROOT CAUSE: 429\nPREVENTION: backoff",
                tool_name="ha_control",
                org_id="org-1",
                agent_id="test-agent",
                scope=MemoryScope.AGENT,
                rca_category="rate_limit",
                rca_prevention="backoff",
            )
        )
        # Promote the learning directly for the test
        for _ in range(5):
            await store.mark_used([lid])
        await store.check_auto_promotions(threshold=5, org_id="org-1")

        content = await _build_with_store(store)
        assert "[rate_limit]" in content

    async def test_learning_without_category_has_no_tag(self) -> None:
        """Promoted tool_correction learnings render unchanged — no [None] prefix."""
        store = InMemoryLearningStore()
        lid = await store.store(
            Learning(
                category="tool_correction",
                trigger_keys=["fan"],
                learning="use fan.bedroom not fan.wrong",
                tool_name="ha_control",
                org_id="org-1",
                agent_id="test-agent",
                scope=MemoryScope.AGENT,
            )
        )
        for _ in range(5):
            await store.mark_used([lid])
        await store.check_auto_promotions(threshold=5, org_id="org-1")

        content = await _build_with_store(store)
        # The learning appears, but no bracketed category prefix
        assert "use fan.bedroom" in content
        assert "[None]" not in content
        assert "[]" not in content


class TestContextBuilderKeptIds:
    """build() returns the ids of learnings that actually survived the budget."""

    async def test_kept_ids_include_injected_learnings(self) -> None:
        store = InMemoryLearningStore()
        lid = await store.store(
            Learning(
                category="tool_correction",
                trigger_keys=["hello"],
                learning="tiny learning",
                tool_name="t",
                org_id="org-1",
                agent_id="test-agent",
                scope=MemoryScope.AGENT,
            )
        )
        identity = AgentIdentity(
            name="test-agent",
            version="1.0",
            description="Test",
            soul_prompt_name="agent.test.soul",
            reasoning_strategy="direct",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        _, kept_ids = await builder.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=_StubPromptManager(),
            learning_store=store,
            agent_id="test-agent",
            org_id="org-1",
        )
        assert lid in kept_ids

    async def test_budget_dropped_learning_not_in_kept_ids(self) -> None:
        """A learning that gets dropped by the token budget must not appear in kept_ids."""
        store = InMemoryLearningStore()
        # Seed two learnings; both match "hello". Long text so only one fits.
        long_text = "x" * 3000
        kept_lid = await store.store(
            Learning(
                category="tool_correction",
                trigger_keys=["hello"],
                learning=f"keep-me {long_text}",
                tool_name="t1",
                org_id="org-1",
                agent_id="test-agent",
                scope=MemoryScope.AGENT,
            )
        )
        dropped_lid = await store.store(
            Learning(
                category="tool_correction",
                trigger_keys=["hello"],
                learning=f"drop-me {long_text}",
                tool_name="t2",
                org_id="org-1",
                agent_id="test-agent",
                scope=MemoryScope.AGENT,
            )
        )
        identity = AgentIdentity(
            name="test-agent",
            version="1.0",
            description="Test",
            soul_prompt_name="agent.test.soul",
            reasoning_strategy="direct",
            memory_config={"learnings": True},
        )
        builder = ContextBuilder()
        messages, kept_ids = await builder.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=_StubPromptManager(),
            learning_store=store,
            agent_id="test-agent",
            org_id="org-1",
            system_token_budget=1000,  # 4000 chars — only room for one long learning
        )
        content = messages[0]["content"]
        assert isinstance(content, str)
        # Exactly one of the two made it into the prompt
        kept_in_prompt = sum(
            1 for tag in ("keep-me", "drop-me") if tag in content
        )
        assert kept_in_prompt == 1
        # kept_ids reflects the dropped one
        assert len(kept_ids) == 1
        assert kept_ids[0] in (kept_lid, dropped_lid)
