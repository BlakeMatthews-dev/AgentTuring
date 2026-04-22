"""Tests for SpecTemplateStore — plan reuse across similar issues.

Spec: specs/phase3-plan-caching.yaml (spec 1011)
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.builders.spec_templates import SpecTemplateStore
from stronghold.types.spec import Invariant, InvariantKind, Spec, SpecStatus


def _verified_spec(
    issue_number: int = 1,
    title: str = "Auth bug fix",
    issue_class: str = "auth",
    **kwargs: object,
) -> Spec:
    defaults: dict[str, object] = {
        "issue_number": issue_number,
        "title": title,
        "invariants": (
            Invariant(
                name="auth_check",
                description="Auth is validated",
                kind=InvariantKind.PRECONDITION,
                expression="True",
            ),
        ),
        "acceptance_criteria": ("User must be authenticated",),
        "status": SpecStatus.VERIFIED,
    }
    defaults.update(kwargs)
    return Spec(**defaults)  # type: ignore[arg-type]


_issue_class = st.sampled_from(["auth", "dependency", "refactor", "test", "protocol"])


class TestSpecTemplateStoreProperties:
    @given(issue_class=_issue_class)
    @settings(max_examples=10)
    def test_template_preserves_invariants(self, issue_class: str) -> None:
        """Invariant: template_preserves_invariants."""
        store = SpecTemplateStore()
        spec = _verified_spec(issue_class=issue_class)
        store.save_template(spec, issue_class)
        adapted = store.adapt(issue_class, issue_number=99, title="New issue")
        assert adapted is not None
        assert len(adapted.invariants) == len(spec.invariants)

    @given(issue_class=_issue_class)
    @settings(max_examples=10)
    def test_adapted_has_new_identity(self, issue_class: str) -> None:
        """Invariant: adapted_has_new_identity."""
        store = SpecTemplateStore()
        store.save_template(_verified_spec(), issue_class)
        adapted = store.adapt(issue_class, issue_number=42, title="New title")
        assert adapted is not None
        assert adapted.issue_number == 42
        assert adapted.title == "New title"

    def test_no_match_returns_none(self) -> None:
        """Invariant: no_match_returns_none."""
        store = SpecTemplateStore()
        assert store.match("nonexistent") is None

    def test_verified_only(self) -> None:
        """Invariant: verified_only — only VERIFIED specs become templates."""
        store = SpecTemplateStore()
        draft = Spec(issue_number=1, title="t", status=SpecStatus.DRAFT)
        stored = store.save_template(draft, "auth")
        assert not stored


class TestSpecTemplateStore:
    def test_save_and_match(self) -> None:
        store = SpecTemplateStore()
        spec = _verified_spec()
        store.save_template(spec, "auth")
        match = store.match("auth")
        assert match is not None
        assert match.title == "Auth bug fix"

    def test_adapt_resets_status_to_active(self) -> None:
        store = SpecTemplateStore()
        store.save_template(_verified_spec(), "auth")
        adapted = store.adapt("auth", issue_number=99, title="New")
        assert adapted is not None
        assert adapted.status == SpecStatus.ACTIVE

    def test_adapt_clears_property_tests(self) -> None:
        store = SpecTemplateStore()
        store.save_template(_verified_spec(), "auth")
        adapted = store.adapt("auth", issue_number=99, title="New")
        assert adapted is not None
        assert adapted.property_tests == ()

    def test_multiple_classes(self) -> None:
        store = SpecTemplateStore()
        store.save_template(_verified_spec(title="Auth fix"), "auth")
        store.save_template(_verified_spec(title="Dep bump"), "dependency")
        assert store.match("auth") is not None
        assert store.match("dependency") is not None
        assert store.match("auth") is not store.match("dependency")

    def test_list_classes(self) -> None:
        store = SpecTemplateStore()
        store.save_template(_verified_spec(), "auth")
        store.save_template(_verified_spec(), "refactor")
        classes = store.list_classes()
        assert "auth" in classes
        assert "refactor" in classes
