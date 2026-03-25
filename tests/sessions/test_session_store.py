"""Tests for InMemorySessionStore CRUD operations."""

import pytest

from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.session import SessionConfig


class TestStoreAndRetrieve:
    """Basic store and retrieve operations."""

    @pytest.mark.asyncio
    async def test_store_and_get_history(self) -> None:
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
        assert history[0]["content"] == "hello"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "hi there"

    @pytest.mark.asyncio
    async def test_messages_in_order(self) -> None:
        store = InMemorySessionStore()
        for i in range(10):
            await store.append_messages(
                "s1",
                [
                    {"role": "user", "content": f"message {i}"},
                ],
            )
        history = await store.get_history("s1")
        for i, msg in enumerate(history):
            assert msg["content"] == f"message {i}"

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self) -> None:
        store = InMemorySessionStore()
        history = await store.get_history("nonexistent")
        assert history == []


class TestSessionIsolation:
    """Multiple sessions are isolated."""

    @pytest.mark.asyncio
    async def test_two_sessions_isolated(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "session 1"}])
        await store.append_messages("s2", [{"role": "user", "content": "session 2"}])
        h1 = await store.get_history("s1")
        h2 = await store.get_history("s2")
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0]["content"] == "session 1"
        assert h2[0]["content"] == "session 2"

    @pytest.mark.asyncio
    async def test_many_sessions_isolated(self) -> None:
        store = InMemorySessionStore()
        for i in range(20):
            await store.append_messages(
                f"s{i}",
                [
                    {"role": "user", "content": f"content for session {i}"},
                ],
            )
        for i in range(20):
            h = await store.get_history(f"s{i}")
            assert len(h) == 1
            assert h[0]["content"] == f"content for session {i}"

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "keep"}])
        await store.append_messages("s2", [{"role": "user", "content": "delete"}])
        await store.delete_session("s2")
        h1 = await store.get_history("s1")
        h2 = await store.get_history("s2")
        assert len(h1) == 1
        assert len(h2) == 0


class TestAppendMessages:
    """Append adds to existing history."""

    @pytest.mark.asyncio
    async def test_append_grows_history(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "first"}])
        await store.append_messages("s1", [{"role": "assistant", "content": "reply"}])
        await store.append_messages("s1", [{"role": "user", "content": "second"}])
        history = await store.get_history("s1")
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_append_multiple_at_once(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_system_messages_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "system", "content": "you are helpful"},
                {"role": "user", "content": "hello"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1  # system messages not stored
        assert history[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_non_string_content_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": 123},  # type: ignore[dict-item]
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 0


class TestMaxMessages:
    """Session max_messages configuration."""

    @pytest.mark.asyncio
    async def test_max_messages_enforced(self) -> None:
        config = SessionConfig(max_messages=5, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        for i in range(20):
            await store.append_messages("s1", [{"role": "user", "content": f"msg {i}"}])
        history = await store.get_history("s1")
        assert len(history) <= 5
        # Should keep the most recent
        assert history[-1]["content"] == "msg 19"

    @pytest.mark.asyncio
    async def test_max_messages_default(self) -> None:
        store = InMemorySessionStore()
        for i in range(50):
            await store.append_messages("s1", [{"role": "user", "content": f"msg {i}"}])
        history = await store.get_history("s1")
        assert len(history) <= 20  # default max_messages


class TestDeleteSession:
    """Session deletion."""

    @pytest.mark.asyncio
    async def test_delete_clears_history(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        await store.delete_session("s1")
        history = await store.get_history("s1")
        assert history == []

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self) -> None:
        store = InMemorySessionStore()
        await store.delete_session("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_delete_then_reuse(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        await store.delete_session("s1")
        await store.append_messages("s1", [{"role": "user", "content": "new"}])
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["content"] == "new"
