"""Tests for ReviewFeedbackExtractor.

Verifies that PR review findings are correctly converted to Learning
objects with appropriate trigger keys, scoping, and content.
"""

from __future__ import annotations

from stronghold.agents.feedback.extractor import ReviewFeedbackExtractor
from stronghold.types.feedback import (
    ReviewFinding,
    ReviewResult,
    Severity,
    ViolationCategory,
)
from stronghold.types.memory import MemoryScope


def _make_result(
    *findings: ReviewFinding,
    pr_number: int = 42,
    agent_id: str = "mason",
) -> ReviewResult:
    return ReviewResult(
        pr_number=pr_number,
        agent_id=agent_id,
        findings=tuple(findings),
        approved=len(findings) == 0,
        summary="Test review",
    )


def _make_finding(
    category: ViolationCategory = ViolationCategory.MOCK_USAGE,
    severity: Severity = Severity.HIGH,
) -> ReviewFinding:
    return ReviewFinding(
        category=category,
        severity=severity,
        file_path="tests/test_foo.py",
        description="unittest.mock detected",
        suggestion="Use fakes from tests/fakes.py",
        line_number=10,
    )


class TestExtractLearnings:
    """ReviewFeedbackExtractor.extract_learnings()."""

    def test_empty_findings_produce_no_learnings(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result()
        learnings = extractor.extract_learnings(result)
        assert learnings == []

    def test_single_finding_produces_one_learning(self) -> None:
        extractor = ReviewFeedbackExtractor()
        finding = _make_finding()
        result = _make_result(finding)
        learnings = extractor.extract_learnings(result)
        assert len(learnings) == 1

    def test_learning_scoped_to_agent(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result(_make_finding(), agent_id="mason")
        learnings = extractor.extract_learnings(result)
        assert learnings[0].agent_id == "mason"
        assert learnings[0].scope == MemoryScope.AGENT

    def test_learning_category_is_review_feedback(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result(_make_finding())
        learnings = extractor.extract_learnings(result)
        assert learnings[0].category == "review_feedback"

    def test_learning_contains_violation_description(self) -> None:
        extractor = ReviewFeedbackExtractor()
        finding = _make_finding(category=ViolationCategory.MOCK_USAGE)
        result = _make_result(finding)
        learnings = extractor.extract_learnings(result)
        assert "[mock_usage]" in learnings[0].learning
        assert "unittest.mock detected" in learnings[0].learning

    def test_learning_contains_suggestion(self) -> None:
        extractor = ReviewFeedbackExtractor()
        finding = _make_finding()
        result = _make_result(finding)
        learnings = extractor.extract_learnings(result)
        assert "Use fakes from tests/fakes.py" in learnings[0].learning

    def test_trigger_keys_match_category(self) -> None:
        extractor = ReviewFeedbackExtractor()
        finding = _make_finding(category=ViolationCategory.ARCHITECTURE_UPDATE)
        result = _make_result(finding)
        learnings = extractor.extract_learnings(result)
        assert "ARCHITECTURE.md" in learnings[0].trigger_keys

    def test_source_query_references_pr(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result(_make_finding(), pr_number=99)
        learnings = extractor.extract_learnings(result)
        assert learnings[0].source_query == "PR #99"

    def test_tool_name_is_auditor(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result(_make_finding())
        learnings = extractor.extract_learnings(result)
        assert learnings[0].tool_name == "auditor"

    def test_multiple_findings_produce_multiple_learnings(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _make_result(
            _make_finding(category=ViolationCategory.MOCK_USAGE),
            _make_finding(category=ViolationCategory.ARCHITECTURE_UPDATE),
            _make_finding(category=ViolationCategory.MISSING_TESTS),
        )
        learnings = extractor.extract_learnings(result)
        assert len(learnings) == 3

    def test_all_categories_have_trigger_keys(self) -> None:
        """Every ViolationCategory maps to non-empty trigger keys."""
        extractor = ReviewFeedbackExtractor()
        for category in ViolationCategory:
            finding = _make_finding(category=category)
            result = _make_result(finding)
            learnings = extractor.extract_learnings(result)
            assert len(learnings) == 1
            assert len(learnings[0].trigger_keys) > 0, f"No trigger keys for {category}"
