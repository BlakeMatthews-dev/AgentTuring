"""Tests for spec-driven verification types.

A Spec is the machine-checkable contract that flows through the builder
pipeline: Quartermaster emits it, Archie scaffolds from it, Mason verifies
against it, Auditor gates on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from stronghold.types.spec import (
    Invariant,
    InvariantKind,
    PropertyTest,
    Spec,
    SpecStatus,
    VerificationResult,
)


# ── Invariant tests ────────────────────────────────────────────────


class TestInvariant:
    def test_defaults(self) -> None:
        inv = Invariant(
            name="no_empty_name",
            description="Agent name must be non-empty",
            kind=InvariantKind.PRECONDITION,
            expression="len(agent.name) > 0",
        )
        assert inv.kind == InvariantKind.PRECONDITION
        assert inv.protocol == ""
        assert inv.severity == "high"

    def test_all_kinds(self) -> None:
        for kind in InvariantKind:
            inv = Invariant(
                name="x",
                description="x",
                kind=kind,
                expression="True",
            )
            assert inv.kind == kind

    def test_frozen(self) -> None:
        inv = Invariant(name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="1")
        try:
            inv.name = "y"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


# ── PropertyTest tests ─────────────────────────────────────────────


class TestPropertyTest:
    def test_defaults(self) -> None:
        pt = PropertyTest(
            name="roundtrip_serialization",
            invariant_name="no_empty_name",
            strategy_code="st.text(min_size=1)",
            test_body="assert deserialize(serialize(x)) == x",
        )
        assert pt.module_path == ""
        assert pt.max_examples == 100

    def test_frozen(self) -> None:
        pt = PropertyTest(
            name="x",
            invariant_name="y",
            strategy_code="st.none()",
            test_body="assert True",
        )
        try:
            pt.name = "z"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


# ── Spec tests ─────────────────────────────────────────────────────


class TestSpec:
    def _make_spec(self, **overrides: object) -> Spec:
        defaults: dict[str, object] = {
            "issue_number": 42,
            "title": "Add caching layer",
            "protocols_touched": ("LLMClient", "LearningStore"),
            "invariants": (
                Invariant(
                    name="cache_hit_returns_same",
                    description="Cached responses must match original",
                    kind=InvariantKind.POSTCONDITION,
                    expression="cache.get(k) == original",
                    protocol="LLMClient",
                ),
            ),
            "acceptance_criteria": (
                "Cache hit returns stored response without LLM call",
                "Cache miss forwards to underlying client",
                "TTL expiry evicts stale entries",
            ),
            "files_touched": (
                "src/stronghold/api/litellm_client.py",
                "src/stronghold/memory/cache.py",
            ),
        }
        defaults.update(overrides)
        return Spec(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        spec = self._make_spec()
        assert spec.issue_number == 42
        assert spec.status == SpecStatus.DRAFT
        assert spec.complexity == "M"
        assert spec.property_tests == ()
        assert isinstance(spec.created_at, datetime)

    def test_frozen(self) -> None:
        spec = self._make_spec()
        try:
            spec.issue_number = 99  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass

    def test_invariant_count(self) -> None:
        spec = self._make_spec()
        assert len(spec.invariants) == 1
        assert spec.invariants[0].name == "cache_hit_returns_same"

    def test_protocols_touched(self) -> None:
        spec = self._make_spec()
        assert "LLMClient" in spec.protocols_touched
        assert "LearningStore" in spec.protocols_touched

    def test_with_property_tests(self) -> None:
        pt = PropertyTest(
            name="cache_roundtrip",
            invariant_name="cache_hit_returns_same",
            strategy_code='st.text(min_size=1, alphabet="ascii")',
            test_body="assert cache.get(key) == value",
            module_path="tests/api/test_cache_properties.py",
        )
        spec = self._make_spec(property_tests=(pt,))
        assert len(spec.property_tests) == 1
        assert spec.property_tests[0].module_path == "tests/api/test_cache_properties.py"

    def test_status_transitions(self) -> None:
        for status in SpecStatus:
            spec = self._make_spec(status=status)
            assert spec.status == status

    def test_to_dict_roundtrip_keys(self) -> None:
        spec = self._make_spec()
        d = spec.to_dict()
        assert d["issue_number"] == 42
        assert d["title"] == "Add caching layer"
        assert d["status"] == "draft"
        assert d["complexity"] == "M"
        assert len(d["invariants"]) == 1
        assert len(d["acceptance_criteria"]) == 3
        assert len(d["files_touched"]) == 2
        assert len(d["protocols_touched"]) == 2
        assert "created_at" in d

    def test_to_dict_with_property_tests(self) -> None:
        pt = PropertyTest(
            name="cache_roundtrip",
            invariant_name="cache_hit_returns_same",
            strategy_code="st.text()",
            test_body="assert True",
        )
        spec = self._make_spec(property_tests=(pt,))
        d = spec.to_dict()
        assert len(d["property_tests"]) == 1
        assert d["property_tests"][0]["name"] == "cache_roundtrip"

    def test_empty_spec_minimal(self) -> None:
        spec = Spec(
            issue_number=1,
            title="Trivial fix",
        )
        assert spec.protocols_touched == ()
        assert spec.invariants == ()
        assert spec.acceptance_criteria == ()
        assert spec.files_touched == ()
        assert spec.property_tests == ()

    def test_invariant_names_property(self) -> None:
        inv1 = Invariant(
            name="a", description="a", kind=InvariantKind.PRECONDITION, expression="True"
        )
        inv2 = Invariant(
            name="b", description="b", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        spec = self._make_spec(invariants=(inv1, inv2))
        assert spec.invariant_names == ("a", "b")

    def test_uncovered_invariants_all_uncovered(self) -> None:
        inv = Invariant(
            name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        spec = self._make_spec(invariants=(inv,))
        assert spec.uncovered_invariants == ("x",)

    def test_uncovered_invariants_all_covered(self) -> None:
        inv = Invariant(
            name="x", description="x", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        pt = PropertyTest(
            name="test_x",
            invariant_name="x",
            strategy_code="st.none()",
            test_body="assert True",
        )
        spec = self._make_spec(invariants=(inv,), property_tests=(pt,))
        assert spec.uncovered_invariants == ()

    def test_uncovered_invariants_partial(self) -> None:
        inv1 = Invariant(
            name="a", description="a", kind=InvariantKind.PRECONDITION, expression="True"
        )
        inv2 = Invariant(
            name="b", description="b", kind=InvariantKind.POSTCONDITION, expression="True"
        )
        pt = PropertyTest(
            name="test_a", invariant_name="a", strategy_code="st.none()", test_body="assert True"
        )
        spec = self._make_spec(invariants=(inv1, inv2), property_tests=(pt,))
        assert spec.uncovered_invariants == ("b",)


# ── VerificationResult tests ──────────────────────────────────────


class TestVerificationResult:
    def test_defaults(self) -> None:
        vr = VerificationResult(
            spec_issue_number=42,
            stage="implement",
            passed=True,
        )
        assert vr.failures == ()
        assert vr.coverage_pct == 0.0
        assert isinstance(vr.verified_at, datetime)

    def test_failed_result(self) -> None:
        vr = VerificationResult(
            spec_issue_number=42,
            stage="review",
            passed=False,
            failures=("invariant 'x' violated: got None, expected str",),
            coverage_pct=50.0,
        )
        assert not vr.passed
        assert len(vr.failures) == 1
        assert vr.coverage_pct == 50.0

    def test_to_dict(self) -> None:
        vr = VerificationResult(
            spec_issue_number=42,
            stage="implement",
            passed=True,
            coverage_pct=100.0,
        )
        d = vr.to_dict()
        assert d["spec_issue_number"] == 42
        assert d["stage"] == "implement"
        assert d["passed"] is True
        assert d["coverage_pct"] == 100.0
        assert "verified_at" in d

    def test_frozen(self) -> None:
        vr = VerificationResult(spec_issue_number=1, stage="x", passed=True)
        try:
            vr.passed = False  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass
