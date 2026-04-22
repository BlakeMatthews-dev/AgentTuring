"""Spec-driven verification types.

A Spec is the machine-checkable contract that flows through the builder
pipeline. Quartermaster emits it, Archie scaffolds property tests from it,
Mason verifies against it, Auditor/Gatekeeper gate on it.

Invariants declare what must hold. PropertyTests prove they hold via
Hypothesis strategies. VerificationResult records whether a pipeline
stage satisfied the spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class InvariantKind(StrEnum):
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    STATE_INVARIANT = "state_invariant"
    DATA_INVARIANT = "data_invariant"


class SpecStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    VERIFIED = "verified"
    VIOLATED = "violated"


@dataclass(frozen=True)
class Invariant:
    """A single machine-checkable property declared by the spec."""

    name: str
    description: str
    kind: InvariantKind
    expression: str
    protocol: str = ""
    severity: Literal["critical", "high", "medium", "low"] = "high"


@dataclass(frozen=True)
class PropertyTest:
    """A Hypothesis-style property test derived from an invariant."""

    name: str
    invariant_name: str
    strategy_code: str
    test_body: str
    module_path: str = ""
    max_examples: int = 100


@dataclass(frozen=True)
class Spec:
    """The spec artifact that anchors a pipeline run.

    Flows through: Quartermaster (emit) → Archie (scaffold) → Mason (verify)
    → Auditor (gate) → Gatekeeper (merge-readiness).
    """

    issue_number: int
    title: str
    protocols_touched: tuple[str, ...] = ()
    invariants: tuple[Invariant, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    property_tests: tuple[PropertyTest, ...] = ()
    complexity: Literal["S", "M", "L"] = "M"
    status: SpecStatus = SpecStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def invariant_names(self) -> tuple[str, ...]:
        return tuple(inv.name for inv in self.invariants)

    @property
    def uncovered_invariants(self) -> tuple[str, ...]:
        covered = {pt.invariant_name for pt in self.property_tests}
        return tuple(name for name in self.invariant_names if name not in covered)

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "title": self.title,
            "status": self.status.value,
            "complexity": self.complexity,
            "protocols_touched": list(self.protocols_touched),
            "invariants": [
                {
                    "name": inv.name,
                    "description": inv.description,
                    "kind": inv.kind.value,
                    "expression": inv.expression,
                    "protocol": inv.protocol,
                    "severity": inv.severity,
                }
                for inv in self.invariants
            ],
            "acceptance_criteria": list(self.acceptance_criteria),
            "files_touched": list(self.files_touched),
            "property_tests": [
                {
                    "name": pt.name,
                    "invariant_name": pt.invariant_name,
                    "strategy_code": pt.strategy_code,
                    "test_body": pt.test_body,
                    "module_path": pt.module_path,
                    "max_examples": pt.max_examples,
                }
                for pt in self.property_tests
            ],
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying a pipeline stage against the spec."""

    spec_issue_number: int
    stage: str
    passed: bool
    failures: tuple[str, ...] = ()
    coverage_pct: float = 0.0
    verified_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_issue_number": self.spec_issue_number,
            "stage": self.stage,
            "passed": self.passed,
            "failures": list(self.failures),
            "coverage_pct": self.coverage_pct,
            "verified_at": self.verified_at.isoformat(),
        }
