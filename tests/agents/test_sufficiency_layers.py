"""Test layered sufficiency: length → heuristic → LLM."""

import pytest

from stronghold.agents.request_analyzer import analyze_request_sufficiency


class TestLengthFloor:
    def test_three_words_always_insufficient(self) -> None:
        result = analyze_request_sufficiency("fix the auth", task_type="code")
        assert not result.sufficient

    def test_five_words_still_insufficient(self) -> None:
        result = analyze_request_sufficiency("fix the login page bug", task_type="code")
        assert not result.sufficient

    def test_ten_words_maybe_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "fix the 401 error in auth.py JWT validation function",
            task_type="code",
        )
        # Has what (fix), where (auth.py), context (JWT) — could be sufficient
        assert result.confidence >= 0.5


class TestHeuristicLayer:
    def test_no_action_verb_insufficient(self) -> None:
        result = analyze_request_sufficiency(
            "the auth middleware in auth.py using JWT tokens",
            task_type="code",
        )
        # Has where + context but no action (what to DO)
        assert "what" in [m.category for m in result.missing]

    def test_no_location_insufficient(self) -> None:
        result = analyze_request_sufficiency(
            "fix the bug where valid JWT tokens return 401",
            task_type="code",
        )
        # Has what + how but no where
        assert "where" in [m.category for m in result.missing]

    def test_all_signals_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "write a function in utils/validators.py that validates email "
            "addresses using regex and returns True for valid emails",
            task_type="code",
        )
        assert result.sufficient
        assert result.confidence >= 0.8
