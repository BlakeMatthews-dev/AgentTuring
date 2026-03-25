"""Tests for request sufficiency analysis.

Validates that analyze_request_sufficiency correctly determines whether
a request has enough detail for a specialist agent, covering edge cases.
"""

from __future__ import annotations

from stronghold.agents.request_analyzer import analyze_request_sufficiency


class TestShortRequestsInsufficient:
    def test_under_6_words_code_insufficient(self) -> None:
        result = analyze_request_sufficiency("fix login", task_type="code")
        assert not result.sufficient

    def test_3_words_code_insufficient(self) -> None:
        result = analyze_request_sufficiency("fix the bug", task_type="code")
        assert not result.sufficient

    def test_single_word_insufficient(self) -> None:
        result = analyze_request_sufficiency("help", task_type="code")
        assert not result.sufficient

    def test_5_words_code_insufficient(self) -> None:
        result = analyze_request_sufficiency("fix the auth bug please", task_type="code")
        assert not result.sufficient

    def test_low_confidence_for_short(self) -> None:
        result = analyze_request_sufficiency("fix it", task_type="code")
        assert result.confidence < 0.3


class TestDetailedRequestsSufficient:
    def test_file_path_and_action_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "Write a Python function in auth.py that validates JWT tokens "
            "and returns True for valid tokens, include pytest tests",
            task_type="code",
        )
        assert result.sufficient
        assert result.confidence >= 0.7

    def test_endpoint_with_behavior_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "Add an endpoint to the FastAPI router that returns 200 with "
            "a JSON body containing user profile data from the database",
            task_type="code",
        )
        assert result.sufficient

    def test_bug_with_location_and_expected(self) -> None:
        result = analyze_request_sufficiency(
            "Fix the bug in middleware/auth.py where the JWT validation "
            "returns 401 even for valid tokens. It should return 200 for valid tokens.",
            task_type="code",
        )
        assert result.sufficient

    def test_high_confidence_for_detailed(self) -> None:
        result = analyze_request_sufficiency(
            "Create a Python class called UserRepository in models/user.py "
            "with CRUD methods that return typed results, add mypy strict checks",
            task_type="code",
        )
        assert result.confidence >= 0.7


class TestQuestionsWithoutSpecifics:
    def test_vague_code_request_has_missing(self) -> None:
        result = analyze_request_sufficiency(
            "make it work better",
            task_type="code",
        )
        assert not result.sufficient
        assert len(result.missing) > 0

    def test_missing_what_category(self) -> None:
        result = analyze_request_sufficiency(
            "the login page needs changes",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "what" in missing_cats

    def test_missing_where_category(self) -> None:
        result = analyze_request_sufficiency(
            "fix the 401 error that happens on login",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "where" in missing_cats

    def test_missing_how_category(self) -> None:
        result = analyze_request_sufficiency(
            "the auth module in auth.py is broken",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "how" in missing_cats

    def test_missing_questions_are_helpful(self) -> None:
        result = analyze_request_sufficiency(
            "something is wrong with login",
            task_type="code",
        )
        for detail in result.missing:
            assert len(detail.question) > 10  # Non-trivial question


class TestEdgeCases:
    def test_empty_string(self) -> None:
        result = analyze_request_sufficiency("", task_type="code")
        assert not result.sufficient
        assert result.confidence <= 0.2

    def test_very_long_request(self) -> None:
        long_text = (
            "Write a Python function called merge_sorted_lists in utils/sorting.py "
            "that takes two sorted lists of integers and returns a single merged sorted list. "
            "The function should use type hints and be O(n+m) complexity. "
            "Add pytest tests that verify edge cases like empty lists, single elements, "
            "and lists with duplicate values. Use mypy strict mode. "
            "The function should return a new list, not modify the input lists."
        )
        result = analyze_request_sufficiency(long_text, task_type="code")
        assert result.sufficient
        assert result.confidence >= 0.7

    def test_unicode_content(self) -> None:
        result = analyze_request_sufficiency(
            "Create a function to validate UTF-8 strings with unicode chars like emoji",
            task_type="code",
        )
        # Should not crash and should have some result
        assert isinstance(result.sufficient, bool)
        assert 0 <= result.confidence <= 1

    def test_automation_short_sufficient(self) -> None:
        result = analyze_request_sufficiency(
            "turn on the bedroom fan",
            task_type="automation",
        )
        assert result.sufficient
        assert result.confidence >= 0.5

    def test_automation_too_short_insufficient(self) -> None:
        result = analyze_request_sufficiency(
            "turn on",
            task_type="automation",
        )
        assert not result.sufficient

    def test_automation_single_word_insufficient(self) -> None:
        result = analyze_request_sufficiency("lights", task_type="automation")
        assert not result.sufficient


class TestSignalDetection:
    def test_what_signal_from_action_verb(self) -> None:
        result = analyze_request_sufficiency(
            "implement a new feature for the dashboard to display user stats",
            task_type="code",
        )
        # "implement" is a what signal
        has_what = "what" not in [m.category for m in result.missing]
        assert has_what

    def test_where_signal_from_file_extension(self) -> None:
        result = analyze_request_sufficiency(
            "update the config in settings.py to increase timeout",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "where" not in missing_cats

    def test_how_signal_from_expected_output(self) -> None:
        result = analyze_request_sufficiency(
            "the function should return True for valid input",
            task_type="code",
        )
        missing_cats = [m.category for m in result.missing]
        assert "how" not in missing_cats

    def test_context_signal_from_framework(self) -> None:
        result = analyze_request_sufficiency(
            "add a FastAPI endpoint that creates new users in PostgreSQL",
            task_type="code",
        )
        # Multiple signals present
        assert result.confidence >= 0.5

    def test_combined_signals_high_confidence(self) -> None:
        result = analyze_request_sufficiency(
            "Create a Python endpoint in auth.py that validates JWT tokens "
            "and returns 200 for valid input",
            task_type="code",
        )
        assert result.confidence >= 0.7
