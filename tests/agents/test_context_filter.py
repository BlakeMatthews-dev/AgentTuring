"""Tests for context filtering.

Verifies that extract_task_context strips noise (greetings, small talk)
and keeps task-relevant messages for specialist agents.
"""

from __future__ import annotations

from stronghold.agents.context_filter import (
    _is_noise,
    _is_relevant,
    extract_task_context,
)


class TestIsNoise:
    def test_greeting_is_noise(self) -> None:
        assert _is_noise("hello")

    def test_hi_is_noise(self) -> None:
        assert _is_noise("hi there")

    def test_thanks_is_noise(self) -> None:
        assert _is_noise("thanks for that")

    def test_short_text_is_noise(self) -> None:
        assert _is_noise("ok")
        assert _is_noise("sure")

    def test_very_short_is_noise(self) -> None:
        assert _is_noise("hi")
        assert _is_noise("ok")

    def test_code_request_not_noise(self) -> None:
        assert not _is_noise("write a function to sort a list of integers")

    def test_error_description_not_noise(self) -> None:
        assert not _is_noise("the endpoint returns a 500 error when I send a POST request")

    def test_bye_is_noise(self) -> None:
        assert _is_noise("goodbye everyone")

    def test_good_morning_is_noise(self) -> None:
        assert _is_noise("good morning team")

    def test_never_mind_is_noise(self) -> None:
        assert _is_noise("never mind about that")

    def test_weather_mention_is_noise(self) -> None:
        assert _is_noise("what is the weather like today")

    def test_empty_string_is_noise(self) -> None:
        assert _is_noise("")

    def test_whitespace_only_is_noise(self) -> None:
        assert _is_noise("   ")


class TestIsRelevant:
    def test_code_keyword_relevant_for_code(self) -> None:
        assert _is_relevant("write a function to parse JSON", "code")

    def test_error_relevant_for_code(self) -> None:
        assert _is_relevant("there is a bug in the auth module", "code")

    def test_file_reference_relevant_for_code(self) -> None:
        assert _is_relevant("update the router.py file", "code")

    def test_framework_relevant_for_code(self) -> None:
        assert _is_relevant("the FastAPI endpoint crashes", "code")

    def test_plain_text_not_relevant_for_code(self) -> None:
        assert not _is_relevant("I had a great day today", "code")

    def test_unknown_task_type_keeps_everything(self) -> None:
        # No signals defined for unknown task type = keep everything
        assert _is_relevant("anything at all", "unknown_type")
        assert _is_relevant("random text", "chat")

    def test_deploy_relevant_for_code(self) -> None:
        assert _is_relevant("deploy the container to kubernetes", "code")

    def test_database_relevant_for_code(self) -> None:
        assert _is_relevant("the database query is slow", "code")


class TestExtractTaskContext:
    def test_empty_messages_returns_empty(self) -> None:
        assert extract_task_context([]) == []

    def test_system_messages_always_kept(self) -> None:
        messages = [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "write a function to parse JSON"},
        ]
        result = extract_task_context(messages, task_type="code")
        roles = [m["role"] for m in result]
        assert "system" in roles

    def test_last_user_message_always_kept(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "write a python class for users"},
        ]
        result = extract_task_context(messages, task_type="code")
        user_msgs = [m for m in result if m["role"] == "user"]
        assert any("python class" in m["content"] for m in user_msgs)

    def test_greetings_stripped_for_code_task(self) -> None:
        messages = [
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "thanks for the help earlier"},
            {"role": "assistant", "content": "You're welcome!"},
            {"role": "user", "content": "write a function to validate email addresses"},
        ]
        result = extract_task_context(messages, task_type="code")
        # Greeting and thanks should be stripped
        contents = [m["content"] for m in result if m["role"] == "user"]
        assert "hello there" not in contents
        assert "thanks for the help earlier" not in contents
        # The actual request should remain
        assert any("validate email" in c for c in contents)

    def test_relevant_messages_kept(self) -> None:
        messages = [
            {"role": "user", "content": "the auth module has a bug in the JWT validation"},
            {"role": "assistant", "content": "I see. What error do you get?"},
            {"role": "user", "content": "it returns 401 even for valid tokens"},
        ]
        result = extract_task_context(messages, task_type="code")
        user_msgs = [m for m in result if m["role"] == "user"]
        # Both messages are code-relevant
        assert len(user_msgs) >= 2

    def test_assistant_response_kept_with_relevant_user(self) -> None:
        messages = [
            {"role": "user", "content": "there is a bug in the database query"},
            {"role": "assistant", "content": "Which query? What error do you see?"},
            {"role": "user", "content": "fix the endpoint"},
        ]
        result = extract_task_context(messages, task_type="code")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1

    def test_off_topic_filtered_for_code(self) -> None:
        messages = [
            {"role": "user", "content": "what is the weather like in portland"},
            {"role": "assistant", "content": "I cannot check weather."},
            {"role": "user", "content": "write a function to sort numbers"},
        ]
        result = extract_task_context(messages, task_type="code")
        user_msgs = [m for m in result if m["role"] == "user"]
        contents = [m["content"] for m in user_msgs]
        assert "weather" not in " ".join(contents)

    def test_single_user_message_kept(self) -> None:
        messages = [{"role": "user", "content": "implement a REST API"}]
        result = extract_task_context(messages, task_type="code")
        assert len(result) == 1
        assert result[0]["content"] == "implement a REST API"

    def test_preserves_message_order(self) -> None:
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "the python import fails"},
            {"role": "assistant", "content": "Which import?"},
            {"role": "user", "content": "fix the import error in auth.py"},
        ]
        result = extract_task_context(messages, task_type="code")
        # System should be first
        assert result[0]["role"] == "system"
        # Order should be maintained
        indices = []
        for r in result:
            for i, m in enumerate(messages):
                if m["content"] == r["content"]:
                    indices.append(i)
                    break
        assert indices == sorted(indices)

    def test_only_system_message_returns_just_system(self) -> None:
        messages = [{"role": "system", "content": "You are an assistant."}]
        result = extract_task_context(messages, task_type="code")
        assert len(result) == 1
        assert result[0]["role"] == "system"
