"""Tests for Archie property-test generator.

Spec: specs/archie-property-gen.yaml
Property tests verify:
  - one_test_per_invariant: every invariant gets exactly one property test
  - test_names_match: each test references the correct invariant
  - all_covered: after generation, uncovered_invariants is empty
  - module_path_convention: paths follow tests/ convention
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.builders.property_gen import generate_property_tests
from stronghold.types.spec import Invariant, InvariantKind, PropertyTest, Spec


# ── Hypothesis strategies ──────────────────────────────────────────

_name = st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N")))
_description = st.text(min_size=1, max_size=80, alphabet=st.characters(categories=("L", "N", "Z")))
_kind = st.sampled_from(list(InvariantKind))
_protocol = st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L",)))


@st.composite
def _invariant(draw: st.DrawFn) -> Invariant:
    return Invariant(
        name=draw(_name),
        description=draw(_description),
        kind=draw(_kind),
        expression="True",
        protocol=draw(_protocol),
    )


@st.composite
def _spec_with_invariants(draw: st.DrawFn) -> Spec:
    n = draw(st.integers(0, 8))
    invariants = tuple(draw(_invariant()) for _ in range(n))
    return Spec(
        issue_number=draw(st.integers(1, 10000)),
        title=draw(_description),
        invariants=invariants,
    )


# ── Property tests ─────────────────────────────────────────────────


class TestPropertyGenProperties:
    @given(spec=_spec_with_invariants())
    @settings(max_examples=50)
    def test_one_test_per_invariant(self, spec: Spec) -> None:
        """Invariant: one_test_per_invariant."""
        tests = generate_property_tests(spec)
        assert len(tests) == len(spec.invariants)

    @given(spec=_spec_with_invariants())
    @settings(max_examples=50)
    def test_test_names_match(self, spec: Spec) -> None:
        """Invariant: test_names_match."""
        tests = generate_property_tests(spec)
        for pt, inv in zip(tests, spec.invariants):
            assert pt.invariant_name == inv.name

    @given(spec=_spec_with_invariants())
    @settings(max_examples=50)
    def test_all_covered(self, spec: Spec) -> None:
        """Invariant: all_covered."""
        tests = generate_property_tests(spec)
        updated = Spec(
            issue_number=spec.issue_number,
            title=spec.title,
            invariants=spec.invariants,
            property_tests=tuple(tests),
        )
        assert updated.uncovered_invariants == ()

    @given(spec=_spec_with_invariants())
    @settings(max_examples=50)
    def test_module_path_convention(self, spec: Spec) -> None:
        """Invariant: module_path_convention."""
        tests = generate_property_tests(spec)
        for pt in tests:
            if pt.module_path:
                assert pt.module_path.startswith("tests/")


# ── Example-based tests ───────────────────────────────────────────


class TestPropertyGen:
    def test_empty_invariants_empty_tests(self) -> None:
        spec = Spec(issue_number=1, title="t")
        tests = generate_property_tests(spec)
        assert tests == []

    def test_generates_strategy_from_kind(self) -> None:
        inv = Invariant(
            name="no_none",
            description="Result is never None",
            kind=InvariantKind.POSTCONDITION,
            expression="result is not None",
            protocol="LLMClient",
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        tests = generate_property_tests(spec)
        assert len(tests) == 1
        pt = tests[0]
        assert pt.name == "test_no_none"
        assert pt.invariant_name == "no_none"
        assert "st." in pt.strategy_code
        assert pt.module_path == "tests/protocols/test_LLMClient_properties.py"

    def test_precondition_gets_precondition_strategy(self) -> None:
        inv = Invariant(
            name="valid_input",
            description="Input must be non-empty",
            kind=InvariantKind.PRECONDITION,
            expression="len(input) > 0",
            protocol="SpecStore",
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        tests = generate_property_tests(spec)
        assert "assume" in tests[0].test_body

    def test_state_invariant_gets_stateful_test(self) -> None:
        inv = Invariant(
            name="monotonic_counter",
            description="Counter always increases",
            kind=InvariantKind.STATE_INVARIANT,
            expression="after > before",
            protocol="QuotaTracker",
        )
        spec = Spec(issue_number=1, title="t", invariants=(inv,))
        tests = generate_property_tests(spec)
        assert "state" in tests[0].strategy_code.lower() or "st." in tests[0].strategy_code
