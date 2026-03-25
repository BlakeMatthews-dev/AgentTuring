"""Tests for session summarization → episodic memory bridge."""

import pytest

from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.sessions.summarizer import SessionSummarizer
from stronghold.types.memory import MemoryScope, MemoryTier


class FakeLLMClient:
    """Fake LLM that returns a canned summary."""

    def __init__(self, response: str = "User discussed Python programming.") -> None:
        self._response = response

    async def complete(self, **kwargs: object) -> dict:
        return {"choices": [{"message": {"content": self._response}}]}

    def stream(self, **kwargs: object):  # type: ignore[no-untyped-def]
        yield ""


class FailingLLMClient:
    """Fake LLM that always raises."""

    async def complete(self, **kwargs: object) -> dict:
        msg = "LLM unavailable"
        raise ConnectionError(msg)

    def stream(self, **kwargs: object):  # type: ignore[no-untyped-def]
        yield ""


class TestBasicSummarization:
    """Session summarization creates episodic memories."""

    @pytest.mark.asyncio
    async def test_summarizes_session(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        memory = await summarizer.summarize_and_bridge(
            "org-1/team-a/blake:chat-001",
            [
                {"role": "user", "content": "How do I write a Python function?"},
                {"role": "assistant", "content": "Here is an example..."},
                {"role": "user", "content": "Can you add type hints?"},
                {"role": "assistant", "content": "Sure, here are type hints..."},
            ],
        )
        assert memory is not None
        assert memory.tier == MemoryTier.OBSERVATION
        assert memory.weight == 0.2
        assert "Python" in memory.content

    @pytest.mark.asyncio
    async def test_observation_scope_is_user(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        memory = await summarizer.summarize_and_bridge(
            "session-1",
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Bye"},
            ],
            user_id="blake",
        )
        assert memory is not None
        assert memory.scope == MemoryScope.USER
        assert memory.user_id == "blake"

    @pytest.mark.asyncio
    async def test_stored_in_episodic(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        await summarizer.summarize_and_bridge(
            "session-1",
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Bye"},
            ],
        )
        assert len(store._memories) == 1


class TestShortSessionSkipped:
    """Sessions too short to summarize."""

    @pytest.mark.asyncio
    async def test_two_messages_returns_none(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        result = await summarizer.summarize_and_bridge(
            "session-1",
            [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_session_returns_none(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        result = await summarizer.summarize_and_bridge("session-1", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_content_messages_skipped(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        result = await summarizer.summarize_and_bridge(
            "session-1",
            [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": ""},
                {"role": "user", "content": "   "},
            ],
        )
        assert result is None


class TestSessionIdParsing:
    """Parse org/team/user from session_id format."""

    @pytest.mark.asyncio
    async def test_full_format(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        memory = await summarizer.summarize_and_bridge(
            "org-emerald/team-core/blake:browser-session",
            [
                {"role": "user", "content": "question 1"},
                {"role": "assistant", "content": "answer 1"},
                {"role": "user", "content": "question 2"},
            ],
        )
        assert memory is not None
        assert memory.org_id == "org-emerald"
        assert memory.team_id == "team-core"
        assert memory.user_id == "blake"

    @pytest.mark.asyncio
    async def test_team_user_format(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        memory = await summarizer.summarize_and_bridge(
            "team-a/blake:session",
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ],
        )
        assert memory is not None
        assert memory.team_id == "team-a"
        assert memory.user_id == "blake"

    @pytest.mark.asyncio
    async def test_explicit_ids_override_parsing(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FakeLLMClient(), store)
        memory = await summarizer.summarize_and_bridge(
            "random-session-id",
            [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"},
                {"role": "user", "content": "q"},
            ],
            org_id="explicit-org",
            team_id="explicit-team",
            user_id="explicit-user",
        )
        assert memory is not None
        assert memory.org_id == "explicit-org"
        assert memory.user_id == "explicit-user"


class TestLLMFailure:
    """Graceful handling when LLM is unavailable."""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self) -> None:
        store = InMemoryEpisodicStore()
        summarizer = SessionSummarizer(FailingLLMClient(), store)
        result = await summarizer.summarize_and_bridge(
            "session-1",
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ],
        )
        assert result is None
        assert len(store._memories) == 0
