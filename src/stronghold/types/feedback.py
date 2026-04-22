"""Types for the RLHF feedback loop between Auditor and Mason.

ViolationCategory enumerates the standard review checks.
ReviewFinding and ReviewResult are the structured output of a PR review.
ViolationMetrics tracks improvement trends over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ViolationCategory(StrEnum):
    """Categories of PR review violations, aligned with Stronghold build rules."""

    MOCK_USAGE = "mock_usage"
    ARCHITECTURE_UPDATE = "architecture_update"
    PROTOCOL_MISSING = "protocol_missing"
    PRODUCTION_CODE_IN_TEST = "production_code_in_test"
    NAMING_STANDARDS = "naming_standards"
    TYPE_ANNOTATIONS = "type_annotations"
    SECURITY = "security"
    HARDCODED_SECRETS = "hardcoded_secrets"
    BUNDLED_CHANGES = "bundled_changes"
    MISSING_TESTS = "missing_tests"
    PRIVATE_FIELD_ACCESS = "private_field_access"
    DI_VIOLATION = "di_violation"
    MISSING_FAKES = "missing_fakes"
    SPEC_COVERAGE_GAP = "spec_coverage_gap"


class Severity(StrEnum):
    """Finding severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ReviewFinding:
    """A single finding from a PR review."""

    category: ViolationCategory
    severity: Severity
    file_path: str
    description: str
    suggestion: str
    line_number: int = 0


@dataclass(frozen=True)
class ReviewResult:
    """Complete result of a PR review."""

    pr_number: int
    agent_id: str
    findings: tuple[ReviewFinding, ...]
    approved: bool
    summary: str
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ViolationMetrics:
    """Tracks violation trends for an agent over time."""

    agent_id: str
    category_counts: dict[ViolationCategory, int] = field(default_factory=dict)
    total_prs_reviewed: int = 0
    total_findings: int = 0
    findings_per_pr_history: list[float] = field(default_factory=list)

    @property
    def findings_per_pr(self) -> float:
        """Average findings per PR."""
        if self.total_prs_reviewed == 0:
            return 0.0
        return self.total_findings / self.total_prs_reviewed

    @property
    def trend(self) -> str:
        """Compute trend from recent history: improving, stable, or regressing."""
        history = self.findings_per_pr_history
        if len(history) < 3:
            return "insufficient_data"
        recent = history[-3:]
        older = history[-6:-3] if len(history) >= 6 else history[:3]
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        delta = recent_avg - older_avg
        if delta < -0.5:
            return "improving"
        if delta > 0.5:
            return "regressing"
        return "stable"
