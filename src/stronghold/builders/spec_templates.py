"""SpecTemplateStore: verified specs become reusable plan templates.

When a Spec passes all verification and the PR merges, it becomes a
template for similar future issues. Quartermaster can match-and-adapt
instead of reasoning from scratch, saving Opus planning budget.
"""

from __future__ import annotations

from stronghold.types.spec import Spec, SpecStatus


class SpecTemplateStore:
    """In-memory store for verified spec templates, keyed by issue class."""

    def __init__(self) -> None:
        self._templates: dict[str, Spec] = {}

    def save_template(self, spec: Spec, issue_class: str) -> bool:
        """Store a verified spec as a template. Returns False if not VERIFIED."""
        if spec.status != SpecStatus.VERIFIED:
            return False
        self._templates[issue_class] = spec
        return True

    def match(self, issue_class: str) -> Spec | None:
        """Find a template for the given issue class."""
        return self._templates.get(issue_class)

    def adapt(
        self,
        issue_class: str,
        *,
        issue_number: int,
        title: str,
    ) -> Spec | None:
        """Adapt a template for a new issue, preserving invariant structure."""
        template = self._templates.get(issue_class)
        if template is None:
            return None
        return Spec(
            issue_number=issue_number,
            title=title,
            protocols_touched=template.protocols_touched,
            invariants=template.invariants,
            acceptance_criteria=template.acceptance_criteria,
            files_touched=(),
            property_tests=(),
            complexity=template.complexity,
            status=SpecStatus.ACTIVE,
        )

    def list_classes(self) -> list[str]:
        """List all stored template classes."""
        return list(self._templates.keys())
