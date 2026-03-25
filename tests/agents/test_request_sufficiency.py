"""Test request sufficiency detection.

Determines if a request has enough detail to route to a specialist,
or if the Conduit needs to reflect back and gather more context.
"""

import pytest

from stronghold.agents.request_analyzer import analyze_request_sufficiency


class TestSufficiency:
    def test_detailed_code_request_is_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "Write a Python function called is_palindrome that takes a string "
            "and returns True if it reads the same forwards and backwards. "
            "Use type hints. Include pytest tests.",
            task_type="code",
        )
        assert result.sufficient
        assert result.confidence > 0.8

    def test_vague_request_is_insufficient(self) -> None:
        result = analyze_request_sufficiency(
            "fix the login",
            task_type="code",
        )
        assert not result.sufficient
        assert len(result.missing) > 0

    def test_medium_request_has_some_missing(self) -> None:
        result = analyze_request_sufficiency(
            "the auth middleware returns 401 on valid JWT tokens",
            task_type="code",
        )
        # Has what (401 on valid tokens) and some where (auth middleware)
        # Missing: which file, which framework, what fix
        assert len(result.missing) > 0

    def test_identifies_missing_what(self) -> None:
        result = analyze_request_sufficiency("the login page", task_type="code")
        assert "what" in [m.category for m in result.missing]

    def test_identifies_missing_where(self) -> None:
        result = analyze_request_sufficiency(
            "fix the 401 error on login",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "where" in missing_cats  # which file?

    def test_identifies_missing_how(self) -> None:
        result = analyze_request_sufficiency(
            "the auth is broken in auth.py",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "how" in missing_cats  # what behavior is expected?

    def test_automation_request(self) -> None:
        result = analyze_request_sufficiency(
            "turn on the bedroom fan",
            task_type="automation",
        )
        # Simple, clear, actionable — sufficient
        assert result.sufficient
