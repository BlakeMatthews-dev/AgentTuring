"""Tests for FakeSpecStore and FakeSpecVerifier."""

from __future__ import annotations

from stronghold.types.spec import (
    Invariant,
    InvariantKind,
    PropertyTest,
    Spec,
    SpecStatus,
    VerificationResult,
)
from tests.fakes import FakeSpecStore, FakeSpecVerifier


def _sample_spec(issue_number: int = 42, **overrides: object) -> Spec:
    defaults: dict[str, object] = {
        "issue_number": issue_number,
        "title": "Test spec",
        "invariants": (
            Invariant(
                name="inv1",
                description="test invariant",
                kind=InvariantKind.POSTCONDITION,
                expression="True",
            ),
        ),
    }
    defaults.update(overrides)
    return Spec(**defaults)  # type: ignore[arg-type]


class TestFakeSpecStore:
    async def test_save_and_get(self) -> None:
        store = FakeSpecStore()
        spec = _sample_spec()
        await store.save(spec)
        retrieved = await store.get(42)
        assert retrieved is spec

    async def test_get_missing(self) -> None:
        store = FakeSpecStore()
        assert await store.get(999) is None

    async def test_list_active_filters_status(self) -> None:
        store = FakeSpecStore()
        draft = _sample_spec(1, status=SpecStatus.DRAFT)
        active = _sample_spec(2, status=SpecStatus.ACTIVE)
        verified = _sample_spec(3, status=SpecStatus.VERIFIED)
        violated = _sample_spec(4, status=SpecStatus.VIOLATED)
        for s in (draft, active, verified, violated):
            await store.save(s)
        result = await store.list_active()
        issue_numbers = {s.issue_number for s in result}
        assert issue_numbers == {1, 2}

    async def test_save_overwrites(self) -> None:
        store = FakeSpecStore()
        spec_v1 = _sample_spec(42, title="v1")
        spec_v2 = _sample_spec(42, title="v2")
        await store.save(spec_v1)
        await store.save(spec_v2)
        retrieved = await store.get(42)
        assert retrieved is not None
        assert retrieved.title == "v2"


class TestFakeSpecVerifier:
    async def test_default_pass(self) -> None:
        verifier = FakeSpecVerifier(default_pass=True)
        spec = _sample_spec()
        result = await verifier.verify(spec, "implement", {})
        assert result.passed is True
        assert result.spec_issue_number == 42

    async def test_default_fail(self) -> None:
        verifier = FakeSpecVerifier(default_pass=False)
        spec = _sample_spec()
        result = await verifier.verify(spec, "implement", {})
        assert result.passed is False

    async def test_override_result(self) -> None:
        verifier = FakeSpecVerifier()
        override = VerificationResult(
            spec_issue_number=42,
            stage="review",
            passed=False,
            failures=("invariant violated",),
            coverage_pct=50.0,
        )
        verifier.set_result(42, "review", override)
        spec = _sample_spec()
        result = await verifier.verify(spec, "review", {})
        assert result is override
        assert not result.passed

    async def test_records_calls(self) -> None:
        verifier = FakeSpecVerifier()
        spec = _sample_spec()
        await verifier.verify(spec, "implement", {})
        await verifier.verify(spec, "review", {})
        assert verifier.verify_calls == [(42, "implement"), (42, "review")]

    async def test_coverage_calculation(self) -> None:
        pt = PropertyTest(
            name="test_inv1",
            invariant_name="inv1",
            strategy_code="st.none()",
            test_body="assert True",
        )
        spec = _sample_spec(property_tests=(pt,))
        verifier = FakeSpecVerifier()
        result = await verifier.verify(spec, "implement", {})
        assert result.coverage_pct == 100.0

    async def test_coverage_zero_when_no_invariants(self) -> None:
        spec = _sample_spec(invariants=())
        verifier = FakeSpecVerifier()
        result = await verifier.verify(spec, "implement", {})
        assert result.coverage_pct == 0.0
