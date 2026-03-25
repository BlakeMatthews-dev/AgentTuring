"""Test that irrelevant chat messages are filtered before reaching the Artificer.

When a user chats casually then asks for code, the Artificer should only
see the relevant context, not greetings, off-topic tangents, etc.
"""

import pytest

from stronghold.agents.context_filter import extract_task_context


class TestContextFiltering:
    def test_strips_greetings(self) -> None:
        """Greetings at the start of conversation should not reach Artificer."""
        messages = [
            {"role": "user", "content": "hey how's it going"},
            {"role": "assistant", "content": "I'm doing well! How can I help?"},
            {"role": "user", "content": "write a function to validate email addresses"},
        ]
        filtered = extract_task_context(messages, task_type="code")
        # Should keep the code request, not the greeting
        user_msgs = [m for m in filtered if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "email" in user_msgs[0]["content"]

    def test_keeps_relevant_context(self) -> None:
        """Messages that provide context for the task should be kept."""
        messages = [
            {"role": "user", "content": "I'm working on a FastAPI app"},
            {"role": "assistant", "content": "Got it, what do you need help with?"},
            {
                "role": "user",
                "content": "the auth middleware is broken, it returns 401 on valid tokens",
            },
            {"role": "assistant", "content": "I see. What auth library are you using?"},
            {"role": "user", "content": "PyJWT. can you fix the bug in auth.py?"},
        ]
        filtered = extract_task_context(messages, task_type="code")
        # Should keep the relevant context about FastAPI, auth, PyJWT
        content = " ".join(m["content"] for m in filtered if m["role"] == "user")
        assert "FastAPI" in content
        assert "401" in content
        assert "PyJWT" in content

    def test_strips_off_topic(self) -> None:
        """Off-topic tangents mid-conversation should be stripped."""
        messages = [
            {"role": "user", "content": "I need to sort a list of users"},
            {"role": "assistant", "content": "Sure, by what field?"},
            {"role": "user", "content": "oh wait, what's the weather like today?"},
            {"role": "assistant", "content": "I don't have weather info."},
            {"role": "user", "content": "ok never mind. sort by last name please"},
        ]
        filtered = extract_task_context(messages, task_type="code")
        content = " ".join(m["content"] for m in filtered if m["role"] == "user")
        assert "weather" not in content
        assert "sort" in content

    def test_preserves_system_message(self) -> None:
        """System messages should always be preserved."""
        messages = [
            {"role": "system", "content": "You are the Artificer."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "write a sorting function"},
        ]
        filtered = extract_task_context(messages, task_type="code")
        system_msgs = [m for m in filtered if m["role"] == "system"]
        assert len(system_msgs) == 1

    def test_last_message_always_kept(self) -> None:
        """The last user message (the trigger) should always be included."""
        messages = [
            {"role": "user", "content": "random chat"},
            {"role": "user", "content": "more random stuff"},
            {"role": "user", "content": "write a function to parse JSON"},
        ]
        filtered = extract_task_context(messages, task_type="code")
        last_user = [m for m in filtered if m["role"] == "user"][-1]
        assert "JSON" in last_user["content"]

    def test_empty_messages(self) -> None:
        filtered = extract_task_context([], task_type="code")
        assert filtered == []

    def test_single_message(self) -> None:
        messages = [{"role": "user", "content": "write code"}]
        filtered = extract_task_context(messages, task_type="code")
        assert len(filtered) == 1
