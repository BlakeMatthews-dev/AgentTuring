"""Tests for real SpecVerifier implementation.

Spec: specs/phase2-verifier.yaml
Tests that the verifier correctly computes coverage and identifies violations.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.builders.verifier import InvariantVerifier
from stronghold.types.spec import (
    Invariant,
    InvariantKind,
    PropertyTest,
    Spec,
)


# ── Hypothesis strategies ──────────────────────────────────────────

_name = st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N")))


@st.composite
def _invariant(draw: st.DrawFn) -> Invariant:
    return Invariant(
        name=draw(_name),
        description=draw(_name),
        kind=InvariantKind.POSTCONDITION,
        expression="True",
    )


@st.composite
def _spec_with_coverage(draw: st.DrawFn) -> Spec:
    n_inv = draw(st.integers(0, 5))
    invariants = tuple(
        Invariant(
            name=f"inv_{i}",
            description=f"inv {i}",
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
    return Spec(
        issue_number=draw(st.integers(1, 1000)),
        title="test",
        invariants=invariants,
        property_tests=tests,
    )


# ── Property tests ─────────────────────────────────────────────────


class TestVerifierProperties:
    @given(spec=_spec_with_coverage())
    @settings(max_examples=50)
    async def test_coverage_accurate(self, spec: Spec) -> None:
        """Invariant: coverage_accurate."""
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "implement", {})
        total = len(spec.invariants)
        covered = len(spec.property_tests)
        expected = (covered / total * 100.0) if total > 0 else 100.0
        assert abs(result.coverage_pct - expected) < 0.01

    @given(spec=_spec_with_coverage())
    @settings(max_examples=50)
    async def test_uncovered_fails(self, spec: Spec) -> None:
        """Invariant: uncovered_fails — uncovered invariants cause failure."""
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "implement", {})
        if spec.uncovered_invariants:
            assert not result.passed
        else:
            assert result.passed

    @given(spec=_spec_with_coverage())
    @settings(max_examples=50)
    async def test_failures_specific(self, spec: Spec) -> None:
        """Invariant: failures_specific — each failure names the invariant."""
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "implement", {})
        for uncovered_name in spec.uncovered_invariants:
            assert any(uncovered_name in f for f in result.failures)


# ── Example-based tests ───────────────────────────────────────────


class TestInvariantVerifier:
    async def test_empty_spec_passes(self) -> None:
        """Invariant: empty_passes."""
        verifier = InvariantVerifier()
        spec = Spec(issue_number=1, title="empty")
        result = await verifier.verify(spec, "implement", {})
        assert result.passed
        assert result.coverage_pct == 100.0
        assert result.failures == ()

    async def test_fully_covered_passes(self) -> None:
        inv = Invariant(
            name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        pt = PropertyTest(
            name="test_x", invariant_name="x", strategy_code="st.none()", test_body="assert True"
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,), property_tests=(pt,))
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "review", {})
        assert result.passed
        assert result.coverage_pct == 100.0

    async def test_uncovered_invariant_fails(self) -> None:
        inv = Invariant(
            name="missing_test", description="no test", kind=InvariantKind.POSTCONDITION,
            expression="True",
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "review", {})
        assert not result.passed
        assert result.coverage_pct == 0.0
        assert any("missing_test" in f for f in result.failures)

    async def test_partial_coverage(self) -> None:
        inv1 = Invariant(name="a", description="a", kind=InvariantKind.POSTCONDITION, expression="T")
        inv2 = Invariant(name="b", description="b", kind=InvariantKind.POSTCONDITION, expression="T")
        pt = PropertyTest(
            name="test_a", invariant_name="a", strategy_code="st.none()", test_body="assert True"
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv1, inv2), property_tests=(pt,))
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "implement", {})
        assert not result.passed
        assert result.coverage_pct == 50.0
        assert any("b" in f for f in result.failures)

    async def test_stage_recorded_in_result(self) -> None:
        spec = Spec(issue_number=42, title="t")
        verifier = InvariantVerifier()
        result = await verifier.verify(spec, "review", {})
        assert result.stage == "review"
        assert result.spec_issue_number == 42
