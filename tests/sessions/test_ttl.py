"""Tests for session TTL expiry."""

import pytest

from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.session import SessionConfig


class TestSessionTTL:
    @pytest.mark.asyncio
    async def test_expired_messages_pruned(self) -> None:
        config = SessionConfig(ttl_seconds=1)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "old"}])

        # Manually age the message
        entries = store._sessions["s1"]
        store._sessions["s1"] = [(e[0], e[1], e[2], e[3] - 10) for e in entries]

        history = await store.get_history("s1")
        assert len(history) == 0
