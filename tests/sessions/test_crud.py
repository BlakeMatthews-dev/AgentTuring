"""Tests for session CRUD."""

import pytest

from stronghold.sessions.store import InMemorySessionStore


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_max_messages_limit(self) -> None:
        store = InMemorySessionStore()
        for i in range(30):
            await store.append_messages(
                "s1",
                [
                    {"role": "user", "content": f"msg {i}"},
                ],
            )
        history = await store.get_history("s1", max_messages=5)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_delete_session(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        await store.delete_session("s1")
        history = await store.get_history("s1")
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_ignores_system_messages(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "system", "content": "you are helpful"},
                {"role": "user", "content": "hello"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["role"] == "user"


class TestSessionEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_messages_ignored(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [])
        history = await store.get_history("s1")
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_tool_messages_ignored(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "tool", "content": "tool result"},
                {"role": "user", "content": "hello"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "from s1"}])
        await store.append_messages("s2", [{"role": "user", "content": "from s2"}])
        h1 = await store.get_history("s1")
        h2 = await store.get_history("s2")
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0]["content"] == "from s1"
        assert h2[0]["content"] == "from s2"

    @pytest.mark.asyncio
    async def test_order_preserved(self) -> None:
        store = InMemorySessionStore()
        for i in range(10):
            await store.append_messages("s1", [{"role": "user", "content": f"msg {i}"}])
        history = await store.get_history("s1")
        for i, msg in enumerate(history):
            assert msg["content"] == f"msg {i}"

    @pytest.mark.asyncio
    async def test_nonexistent_session_returns_empty(self) -> None:
        store = InMemorySessionStore()
        history = await store.get_history("nonexistent")
        assert history == []

    @pytest.mark.asyncio
    async def test_delete_only_affects_target(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "keep"}])
        await store.append_messages("s2", [{"role": "user", "content": "delete"}])
        await store.delete_session("s2")
        assert len(await store.get_history("s1")) == 1
        assert len(await store.get_history("s2")) == 0
