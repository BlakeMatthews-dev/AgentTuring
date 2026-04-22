"""Tests for spec coverage checker.

Spec: specs/phase2-verifier.yaml (spec 1010)
Tests that uncovered invariants produce SPEC_COVERAGE_GAP findings.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.builders.spec_coverage import check_spec_coverage
from stronghold.types.feedback import ViolationCategory
from stronghold.types.spec import Invariant, InvariantKind, PropertyTest, Spec


@st.composite
def _spec_with_partial_coverage(draw: st.DrawFn) -> Spec:
    n_inv = draw(st.integers(0, 5))
    invariants = tuple(
        Invariant(
            name=f"inv_{i}",
            description=f"test invariant {i}",
            kind=InvariantKind.POSTCONDITION,
            expression="True",
        )
        for i in range(n_inv)
    )
    n_covered = draw(st.integers(0, n_inv))
    tests = tuple(
        PropertyTest(
            name=f"test_inv_{i}",
            invariant_name=f"inv_{i}",
            strategy_code="st.none()",
            test_body="assert True",
        )
        for i in range(n_covered)
    )
    return Spec(issue_number=1, title="t", invariants=invariants, property_tests=tests)


class TestSpecCoverageProperties:
    @given(spec=_spec_with_partial_coverage())
    @settings(max_examples=50)
    def test_finding_count_matches_uncovered(self, spec: Spec) -> None:
        """Invariant: uncovered_produces_finding."""
        findings = check_spec_coverage(spec)
        assert len(findings) == len(spec.uncovered_invariants)

    @given(spec=_spec_with_partial_coverage())
    @settings(max_examples=50)
    def test_all_findings_are_spec_coverage_gap(self, spec: Spec) -> None:
        findings = check_spec_coverage(spec)
        for f in findings:
            assert f.category == ViolationCategory.SPEC_COVERAGE_GAP

    @given(spec=_spec_with_partial_coverage())
    @settings(max_examples=50)
    def test_covered_produces_no_findings(self, spec: Spec) -> None:
        """Invariant: covered_no_finding."""
        findings = check_spec_coverage(spec)
        if not spec.uncovered_invariants:
            assert findings == []


class TestSpecCoverage:
    def test_none_spec_returns_empty(self) -> None:
        """Invariant: backward_compatible."""
        assert check_spec_coverage(None) == []

    def test_uncovered_invariant_produces_finding(self) -> None:
        inv = Invariant(
            name="x", description="must hold", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        findings = check_spec_coverage(spec)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.SPEC_COVERAGE_GAP
        assert "x" in findings[0].description

    def test_fully_covered_produces_no_findings(self) -> None:
        inv = Invariant(
            name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        pt = PropertyTest(
            name="test_x", invariant_name="x", strategy_code="st.none()", test_body="assert True"
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,), property_tests=(pt,))
        assert check_spec_coverage(spec) == []

    def test_severity_is_critical(self) -> None:
        inv = Invariant(
            name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        findings = check_spec_coverage(spec)
        from stronghold.types.feedback import Severity
        assert findings[0].severity == Severity.CRITICAL
