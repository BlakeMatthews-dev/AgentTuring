"""Real SpecVerifier: checks invariant coverage and reports violations.

Verifies that every invariant in a Spec has a corresponding PropertyTest.
Invariants without property tests are reported as failures.
"""

from __future__ import annotations

from typing import Any

from stronghold.types.spec import Spec, VerificationResult


class InvariantVerifier:
    """Verifies spec invariants by checking property test coverage."""

    async def verify(self, spec: Spec, stage: str, result: dict[str, Any]) -> VerificationResult:
        total = len(spec.invariants)
        if total == 0:
            return VerificationResult(
                spec_issue_number=spec.issue_number,
                stage=stage,
                passed=True,
                coverage_pct=100.0,
            )

        uncovered = spec.uncovered_invariants
        covered = total - len(uncovered)
        coverage = covered / total * 100.0

        failures = tuple(f"Invariant '{name}' has no property test" for name in uncovered)

        return VerificationResult(
            spec_issue_number=spec.issue_number,
            stage=stage,
            passed=len(uncovered) == 0,
            failures=failures,
            coverage_pct=coverage,
        )
