"""Test that Conduit gathers context before routing to specialists.

The Conduit stays in chat mode until it has enough detail to create
a good task for a specialist agent. It asks follow-up questions to
collect the detail needed.
"""

import pytest

from stronghold.classifier.engine import ClassifierEngine, is_ambiguous
from stronghold.classifier.keyword import score_keywords
from stronghold.types.config import TaskTypeConfig


TASK_TYPES = {
    "code": TaskTypeConfig(keywords=["code", "function", "bug", "fix", "error", "implement"]),
    "chat": TaskTypeConfig(keywords=["hello", "hi", "help"]),
    "search": TaskTypeConfig(keywords=["search", "find", "look up"]),
    "automation": TaskTypeConfig(keywords=["fan", "light", "turn on", "turn off"]),
}


class TestSignalDetection:
    """Test that the classifier detects when to switch from chat to specialist."""

    def test_vague_request_stays_chat(self) -> None:
        """'I need help with the login' — not enough for code, could be anything."""
        scores = score_keywords("I need help with the login page", TASK_TYPES)
        # "help" matches chat — single intent, not ambiguous, stays in chat
        above_zero = {k: v for k, v in scores.items() if v > 0}
        # Should not confidently switch to code
        assert scores.get("code", 0) < 3.0

    def test_specific_request_triggers_code(self) -> None:
        """'fix the bug in the auth function' — clear code signal."""
        scores = score_keywords("fix the bug in the auth function", TASK_TYPES)
        assert scores.get("code", 0) >= 3.0  # strong indicator

    def test_progressive_detail_builds_signal(self) -> None:
        """Simulate a conversation where detail accumulates."""
        # Turn 1: vague
        s1 = score_keywords("the login is broken", TASK_TYPES)
        assert s1.get("code", 0) < 3.0

        # Turn 2: more specific
        s2 = score_keywords("it throws a 401 error when I submit valid credentials", TASK_TYPES)
        assert s2.get("code", 0) >= 1.0  # "error" matches

        # Turn 3: very specific — combined context would be strong
        s3 = score_keywords(
            "fix the bug in auth.py where the JWT audience check is disabled", TASK_TYPES
        )
        assert s3.get("code", 0) >= 3.0  # "fix the bug" strong indicator

    def test_automation_clear_signal(self) -> None:
        """'turn on the fan' — immediate, no context gathering needed."""
        scores = score_keywords("turn on the fan", TASK_TYPES)
        assert scores.get("automation", 0) >= 3.0  # strong indicator

    def test_search_needs_specificity(self) -> None:
        """'find me something' vs 'search for Python sorting algorithms'."""
        vague = score_keywords("find me something interesting", TASK_TYPES)
        specific = score_keywords("search for Python sorting algorithms", TASK_TYPES)
        assert specific.get("search", 0) > vague.get("search", 0)


class TestContextSufficiency:
    """Test whether enough context exists to route to a specialist."""

    def test_short_message_insufficient(self) -> None:
        """Very short messages rarely have enough context for specialists."""
        scores = score_keywords("fix it", TASK_TYPES)
        code_score = scores.get("code", 0)
        # "fix" matches code keyword (+1) but not strong enough
        assert code_score < 3.0

    def test_detailed_message_sufficient(self) -> None:
        """Detailed messages can route immediately."""
        scores = score_keywords(
            "write a function that takes a list of integers and returns "
            "the two numbers that sum to a target value",
            TASK_TYPES,
        )
        assert scores.get("code", 0) >= 3.0  # "write a function" strong
