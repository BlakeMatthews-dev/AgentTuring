"""Tests for canary block injection in ContextBuilder (S1.1)."""

from __future__ import annotations

from stronghold.agents.context_builder import ContextBuilder, inject_cache_breakpoints
from stronghold.types.agent import AgentIdentity
from tests.fakes import FakePromptManager, InMemoryCanaryStore


def _make_identity(name: str = "test-agent") -> AgentIdentity:
    return AgentIdentity(
        name=name,
        reasoning_strategy="direct",
        memory_config={},
    )


async def test_canary_block_injected_when_store_configured() -> None:
    """Canary block appears between soul and promoted learnings."""
    pm = FakePromptManager()
    pm.seed("agent.test-agent.soul", "You are a helpful assistant.")
    store = InMemoryCanaryStore()
    token = await store.get_or_mint("sess-1", "org-1")

    cb = ContextBuilder()
    messages = await cb.build(
        [{"role": "user", "content": "hello"}],
        _make_identity(),
        prompt_manager=pm,
        canary_store=store,
        session_id="sess-1",
        org_id="org-1",
    )

    system_content = messages[0]["content"]
    assert "<stronghold:canary>" in system_content
    assert token in system_content
    # Canary appears after soul
    soul_pos = system_content.find("You are a helpful assistant.")
    canary_pos = system_content.find("<stronghold:canary>")
    assert canary_pos > soul_pos


async def test_canary_block_absent_when_store_unconfigured() -> None:
    """Back-compat: no canary_store → no canary block injected."""
    pm = FakePromptManager()
    pm.seed("agent.test-agent.soul", "You are a helpful assistant.")

    cb = ContextBuilder()
    messages = await cb.build(
        [{"role": "user", "content": "hello"}],
        _make_identity(),
        prompt_manager=pm,
        org_id="org-1",
    )

    system_content = messages[0]["content"]
    assert "<stronghold:canary>" not in system_content


async def test_canary_block_excluded_from_cache_breakpoint() -> None:
    """AC 6: inject_cache_breakpoints splits before the canary block (not cached)."""
    pm = FakePromptManager()
    pm.seed("agent.test-agent.soul", "You are a helpful assistant.")
    store = InMemoryCanaryStore()

    cb = ContextBuilder()
    messages = await cb.build(
        [{"role": "user", "content": "hello"}],
        _make_identity(),
        prompt_manager=pm,
        canary_store=store,
        session_id="sess-cache",
        org_id="org-1",
        enable_cache_breakpoints=True,
    )

    system_content = messages[0]["content"]
    # With cache breakpoints, content is a list of blocks
    assert isinstance(system_content, list)
    # The first block (soul, stable) has cache_control
    first_block = system_content[0]
    assert "cache_control" in first_block
    # The canary token should NOT be in the cached (first) block
    canary_in_cached = "<stronghold:canary>" in first_block.get("text", "")
    assert not canary_in_cached, "Canary block must not be in the cached stable prefix"
