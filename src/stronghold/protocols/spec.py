"""Protocols for spec-driven verification.

SpecStore: persists and retrieves Spec artifacts across pipeline runs.
SpecVerifier: checks whether a pipeline stage satisfies a Spec.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.spec import Spec, VerificationResult


@runtime_checkable
class SpecStore(Protocol):
    """Persists Spec artifacts so they flow across pipeline stages."""

    async def save(self, spec: Spec) -> None:
        """Store or update a spec keyed by issue_number."""
        ...

    async def get(self, issue_number: int) -> Spec | None:
        """Retrieve a spec by issue number. Returns None if not found."""
        ...

    async def list_active(self) -> list[Spec]:
        """Return all specs with status ACTIVE or DRAFT."""
        ...


@runtime_checkable
class SpecVerifier(Protocol):
    """Checks whether a pipeline stage satisfies a Spec's invariants."""

    async def verify(self, spec: Spec, stage: str, result: dict[str, object]) -> VerificationResult:
        """Verify stage output against spec invariants.

        Returns a VerificationResult with pass/fail, failure details,
        and coverage percentage (property tests covering invariants).
        """
        ...
