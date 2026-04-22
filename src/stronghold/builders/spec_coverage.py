"""Spec coverage checker: produces ReviewFindings for uncovered invariants.

Used by the Auditor to gate PRs on spec invariant coverage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.types.feedback import ReviewFinding, Severity, ViolationCategory

if TYPE_CHECKING:
    from stronghold.types.spec import Spec


def check_spec_coverage(spec: Spec | None) -> list[ReviewFinding]:
    """Check a Spec for uncovered invariants and return findings.

    Returns an empty list if the spec is None or fully covered.
    """
    if spec is None:
        return []

    findings: list[ReviewFinding] = []
    for name in spec.uncovered_invariants:
        inv = next(inv for inv in spec.invariants if inv.name == name)
        findings.append(
            ReviewFinding(
                category=ViolationCategory.SPEC_COVERAGE_GAP,
                severity=Severity.CRITICAL,
                file_path="",
                description=f"Invariant '{name}' has no property test: {inv.description}",
                suggestion=f"Add a property test covering invariant '{name}'",
            )
        )
    return findings
