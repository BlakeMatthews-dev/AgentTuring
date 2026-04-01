"""ReviewFeedbackExtractor — converts PR review findings into Learning objects.

This is the bridge between the Auditor's structured review output and
Mason's learning memory. Each ReviewFinding becomes a Learning with
trigger_keys derived from the violation category, scoped to the
authoring agent.
"""

from __future__ import annotations

from stronghold.types.feedback import ReviewResult, ViolationCategory
from stronghold.types.memory import Learning, MemoryScope

# Maps each violation category to trigger keys that will match
# when the agent encounters similar patterns in future work.
_CATEGORY_TRIGGER_KEYS: dict[ViolationCategory, list[str]] = {
    ViolationCategory.MOCK_USAGE: [
        "unittest.mock",
        "MagicMock",
        "AsyncMock",
        "patch",
        "mock",
        "test",
        "fakes",
    ],
    ViolationCategory.ARCHITECTURE_UPDATE: [
        "ARCHITECTURE.md",
        "new module",
        "architecture",
        "documentation",
    ],
    ViolationCategory.PROTOCOL_MISSING: [
        "protocol",
        "interface",
        "protocols/",
        "DI",
        "dependency injection",
    ],
    ViolationCategory.PRODUCTION_CODE_IN_TEST: [
        "test PR",
        "src/",
        "production code",
        "test-only",
    ],
    ViolationCategory.NAMING_STANDARDS: [
        "naming",
        "component name",
        "CLAUDE.md",
        "roster",
        "agent name",
    ],
    ViolationCategory.TYPE_ANNOTATIONS: [
        "Any",
        "type annotation",
        "mypy",
        "strict",
        "return type",
    ],
    ViolationCategory.SECURITY: [
        "security",
        "vulnerability",
        "injection",
        "auth",
        "header trust",
    ],
    ViolationCategory.HARDCODED_SECRETS: [
        "secret",
        "credential",
        "API key",
        "hardcoded",
        "env var",
    ],
    ViolationCategory.BUNDLED_CHANGES: [
        "bundled",
        "scope",
        "focused",
        "one PR",
        "split",
    ],
    ViolationCategory.MISSING_TESTS: [
        "test",
        "TDD",
        "coverage",
        "test file",
    ],
    ViolationCategory.PRIVATE_FIELD_ACCESS: [
        "private field",
        "._",
        "internal",
        "protocol method",
    ],
    ViolationCategory.DI_VIOLATION: [
        "concrete import",
        "DI",
        "protocol",
        "container",
        "dependency",
    ],
    ViolationCategory.MISSING_FAKES: [
        "fake",
        "fakes.py",
        "test double",
        "protocol",
        "noop",
    ],
}


class ReviewFeedbackExtractor:
    """Converts ReviewResult findings into Learning objects.

    Implements the FeedbackExtractor protocol.
    """

    def extract_learnings(self, result: ReviewResult) -> list[Learning]:
        """Convert each finding into a Learning scoped to the authoring agent."""
        learnings: list[Learning] = []
        for finding in result.findings:
            trigger_keys = _CATEGORY_TRIGGER_KEYS.get(
                finding.category,
                [finding.category.value],
            )
            learning = Learning(
                category="review_feedback",
                trigger_keys=list(trigger_keys),
                learning=(
                    f"[{finding.category.value}] {finding.description}. Fix: {finding.suggestion}"
                ),
                tool_name="auditor",
                source_query=f"PR #{result.pr_number}",
                agent_id=result.agent_id,
                scope=MemoryScope.AGENT,
            )
            learnings.append(learning)
        return learnings
