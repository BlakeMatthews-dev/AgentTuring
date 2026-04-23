"""Tests for prompt caching support in ContextBuilder.

Spec: specs/prompt-caching.yaml
Invariants tested via Hypothesis property tests:
  - cache_only_stable_prefix: dynamic learnings never get cache_control
  - idempotent_annotation: applying twice == applying once
  - message_count_preserved: never adds or removes messages
  - non_system_untouched: user/assistant messages pass through unchanged
  - backward_compatible_default: build() without caching returns string content
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.agents.context_builder import ContextBuilder, inject_cache_breakpoints


# ── Hypothesis strategies ──────────────────────────────────────────

_LEARNINGS_BOUNDARY = "<stronghold:corrections"

_role = st.sampled_from(["user", "assistant"])
_text = st.text(min_size=1, max_size=200, alphabet=st.characters(categories=("L", "N", "P", "Z")))


@st.composite
def _system_message_with_learnings(draw: st.DrawFn) -> dict[str, Any]:
    soul = draw(_text)
    learnings = f"{_LEARNINGS_BOUNDARY}>{draw(_text)}</stronghold:corrections>"
    return {"role": "system", "content": f"{soul}\n\n{learnings}"}


@st.composite
def _system_message_plain(draw: st.DrawFn) -> dict[str, Any]:
    return {"role": "system", "content": draw(_text)}


@st.composite
def _non_system_message(draw: st.DrawFn) -> dict[str, Any]:
    return {"role": draw(_role), "content": draw(_text)}


@st.composite
def _message_list_with_system(draw: st.DrawFn) -> list[dict[str, Any]]:
    system = draw(st.one_of(_system_message_plain(), _system_message_with_learnings()))
    others = draw(st.lists(_non_system_message(), min_size=0, max_size=5))
    return [system, *others]


@st.composite
def _message_list_no_system(draw: st.DrawFn) -> list[dict[str, Any]]:
    return draw(st.lists(_non_system_message(), min_size=1, max_size=5))


# ── Property tests (spec invariants) ──────────────────────────────


class TestCacheBreakpointProperties:
    """Property-based tests derived from specs/prompt-caching.yaml invariants."""

    @given(msgs=_message_list_with_system())
    @settings(max_examples=50)
    def test_message_count_preserved(self, msgs: list[dict[str, Any]]) -> None:
        """Invariant: message_count_preserved."""
        result = inject_cache_breakpoints(msgs)
        assert len(result) == len(msgs)

    @given(msgs=_message_list_with_system())
    @settings(max_examples=50)
    def test_non_system_untouched(self, msgs: list[dict[str, Any]]) -> None:
        """Invariant: non_system_untouched."""
        result = inject_cache_breakpoints(msgs)
        for inp, out in zip(msgs[1:], result[1:]):
            assert out == inp

    @given(msgs=_message_list_with_system())
    @settings(max_examples=50)
    def test_idempotent_annotation(self, msgs: list[dict[str, Any]]) -> None:
        """Invariant: idempotent_annotation."""
        once = inject_cache_breakpoints(msgs)
        twice = inject_cache_breakpoints(once)
        assert once == twice

    @given(msgs=_message_list_with_system())
    @settings(max_examples=50)
    def test_cache_only_stable_prefix(self, msgs: list[dict[str, Any]]) -> None:
        """Invariant: cache_only_stable_prefix — dynamic blocks have no cache_control."""
        result = inject_cache_breakpoints(msgs)
        system_msg = result[0]
        content = system_msg["content"]
        if isinstance(content, list) and len(content) > 1:
            for block in content[1:]:
                assert "cache_control" not in block

    @given(msgs=_message_list_no_system())
    @settings(max_examples=20)
    def test_no_system_passthrough(self, msgs: list[dict[str, Any]]) -> None:
        """No system message → messages returned unchanged."""
        result = inject_cache_breakpoints(msgs)
        assert result == msgs

    @given(msgs=_message_list_with_system())
    @settings(max_examples=50)
    def test_first_block_always_cached(self, msgs: list[dict[str, Any]]) -> None:
        """The first (stable) content block always gets cache_control."""
        result = inject_cache_breakpoints(msgs)
        system_msg = result[0]
        content = system_msg["content"]
        assert isinstance(content, list)
        assert content[0].get("cache_control") == {"type": "ephemeral"}


# ── Example-based tests ───────────────────────────────────────────


class TestInjectCacheBreakpoints:
    def test_marks_system_message_with_cache_control(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "hello"},
        ]
        result = inject_cache_breakpoints(messages)
        system_msg = result[0]
        assert system_msg["role"] == "system"
        assert isinstance(system_msg["content"], list)
        assert system_msg["content"][0]["type"] == "text"
        assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_already_block_format_system_message(self) -> None:
        messages = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "soul prompt"},
                    {"type": "text", "text": "dynamic learnings"},
                ],
            },
        ]
        result = inject_cache_breakpoints(messages)
        blocks = result[0]["content"]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_string_content_split_at_boundary(self) -> None:
        soul = "You are an agent."
        learnings = "<stronghold:corrections>learning1</stronghold:corrections>"
        combined = f"{soul}\n\n{learnings}"
        messages = [{"role": "system", "content": combined}]
        result = inject_cache_breakpoints(messages)
        blocks = result[0]["content"]
        assert len(blocks) == 2
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_system_without_learnings_single_block(self) -> None:
        messages = [{"role": "system", "content": "Just a soul prompt."}]
        result = inject_cache_breakpoints(messages)
        blocks = result[0]["content"]
        assert len(blocks) == 1
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}


# ── ContextBuilder integration tests ──────────────────────────────


class TestContextBuilderCaching:
    async def test_build_with_caching_enabled(self) -> None:
        from stronghold.types.agent import AgentIdentity

        identity = AgentIdentity(
            name="test-agent",
            version="1.0",
            description="Test",
            soul_prompt_name="agent.test.soul",
            reasoning_strategy="direct",
        )

        class StubPromptManager:
            async def get(self, name: str, *, label: str = "active") -> str:
                return "You are a test agent."

            async def get_with_config(
                self, name: str, *, label: str = "active"
            ) -> tuple[str, dict]:
                return "You are a test agent.", {}

            async def upsert(
                self, name: str, content: str, *, config: dict | None = None, label: str = "active"
            ) -> None:
                pass

        builder = ContextBuilder()
        messages = [{"role": "user", "content": "hello"}]
        result, _ = await builder.build(
            messages,
            identity,
            prompt_manager=StubPromptManager(),
            enable_cache_breakpoints=True,
        )

        system_msg = result[0]
        assert system_msg["role"] == "system"
        assert isinstance(system_msg["content"], list)
        assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    async def test_build_without_caching_returns_string_content(self) -> None:
        """Invariant: backward_compatible_default."""
        from stronghold.types.agent import AgentIdentity

        identity = AgentIdentity(
            name="test-agent",
            version="1.0",
            description="Test",
            soul_prompt_name="agent.test.soul",
            reasoning_strategy="direct",
        )

        class StubPromptManager:
            async def get(self, name: str, *, label: str = "active") -> str:
                return "You are a test agent."

            async def get_with_config(
                self, name: str, *, label: str = "active"
            ) -> tuple[str, dict]:
                return "You are a test agent.", {}

            async def upsert(
                self, name: str, content: str, *, config: dict | None = None, label: str = "active"
            ) -> None:
                pass

        builder = ContextBuilder()
        messages = [{"role": "user", "content": "hello"}]
        result, _ = await builder.build(
            messages,
            identity,
            prompt_manager=StubPromptManager(),
        )

        system_msg = result[0]
        assert system_msg["role"] == "system"
        assert isinstance(system_msg["content"], str)
