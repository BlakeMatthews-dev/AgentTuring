"""Test the reflect-back-then-clarify pattern.

Before routing to a specialist, the Conduit should:
1. Summarize what it understood
2. Allow corrections
3. Ask clarifying questions
4. Only then submit to the specialist
"""

import pytest

from stronghold.agents.context_filter import extract_task_context


class TestReflectBackPattern:
    def test_sufficient_context_no_reflection_needed(self) -> None:
        """If the request is already detailed, skip reflection."""
        messages = [
            {
                "role": "user",
                "content": (
                    "Write a Python function called is_palindrome that takes a string "
                    "and returns True if it reads the same forwards and backwards. "
                    "Use type hints. Include pytest tests. Handle edge cases like "
                    "empty strings and single characters."
                ),
            },
        ]
        # This is detailed enough — no need to reflect back
        filtered = extract_task_context(messages, task_type="code")
        assert len(filtered) == 1
        assert "palindrome" in filtered[0]["content"]

    def test_vague_request_needs_reflection(self) -> None:
        """If the request is vague, we need to gather more detail."""
        messages = [
            {"role": "user", "content": "fix the login"},
        ]
        # This is too vague — the Conduit should ask follow-ups
        # We can measure vagueness by word count and specificity
        content = messages[0]["content"]
        is_vague = len(content.split()) < 6 and not any(
            kw in content.lower() for kw in ["function", "class", "file", "error", "401", "500"]
        )
        assert is_vague

    def test_multi_turn_builds_complete_context(self) -> None:
        """Simulate the full reflect-clarify-submit flow."""
        # Turn 1: User makes vague request
        turn1 = {"role": "user", "content": "the auth is broken"}

        # Turn 2: Conduit reflects back + asks questions
        turn2 = {
            "role": "assistant",
            "content": (
                "I understand you're having an auth issue. Let me clarify:\n"
                "a) What type of auth? (JWT, OAuth, session)\n"
                "b) What's the error? (401, 403, crash)\n"
                "c) Which file is it in?"
            ),
        }

        # Turn 3: User provides detail
        turn3 = {
            "role": "user",
            "content": (
                "JWT auth. It returns 401 even with a valid token. "
                "The file is auth.py and we're using PyJWT."
            ),
        }

        # Turn 4: Conduit summarizes final understanding
        turn4 = {
            "role": "assistant",
            "content": (
                "Got it. I'll fix the JWT validation in auth.py where valid tokens "
                "get 401 responses. Using PyJWT. Let me work on that."
            ),
        }

        messages = [turn1, turn2, turn3, turn4]

        # Filter for Artificer — should keep the detailed turns
        filtered = extract_task_context(messages, task_type="code")
        content = " ".join(m.get("content", "") for m in filtered)
        assert "JWT" in content
        assert "401" in content
        assert "auth.py" in content
        assert "PyJWT" in content
