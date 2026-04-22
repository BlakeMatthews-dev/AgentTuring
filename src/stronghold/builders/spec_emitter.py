"""Quartermaster spec emission: converts issue metadata into a machine-checkable Spec.

Called during the decompose stage. Each atomic issue gets a Spec with
acceptance criteria extracted from the issue body, invariants derived
from criteria, and protocols inferred from file paths.
"""

from __future__ import annotations

import re
from typing import Literal

from stronghold.types.spec import Invariant, InvariantKind, Spec, SpecStatus

_COMPLEXITY_MAP: dict[str, Literal["S", "M", "L"]] = {
    "simple": "S",
    "moderate": "M",
    "complex": "L",
}

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)
_PROTOCOL_PATH_RE = re.compile(r"src/stronghold/protocols/(\w+)\.py")


def _extract_criteria(body: str) -> tuple[str, ...]:
    return tuple(m.group(1).strip() for m in _BULLET_RE.finditer(body))


def _infer_protocols(files: list[str]) -> tuple[str, ...]:
    protocols: list[str] = []
    for f in files:
        m = _PROTOCOL_PATH_RE.search(f)
        if m:
            protocols.append(m.group(1))
    return tuple(dict.fromkeys(protocols))


def _criteria_to_invariants(criteria: tuple[str, ...]) -> tuple[Invariant, ...]:
    return tuple(
        Invariant(
            name=f"criterion_{i}",
            description=c,
            kind=InvariantKind.POSTCONDITION,
            expression=f"# verify: {c}",
        )
        for i, c in enumerate(criteria)
    )


def emit_spec(
    *,
    issue_number: int,
    title: str,
    body: str = "",
    complexity: str = "moderate",
    files_touched: list[str] | None = None,
) -> Spec:
    """Emit a Spec from issue metadata."""
    criteria = _extract_criteria(body)
    files = files_touched or []
    protocols = _infer_protocols(files)
    invariants = _criteria_to_invariants(criteria)

    return Spec(
        issue_number=issue_number,
        title=title,
        protocols_touched=protocols,
        invariants=invariants,
        acceptance_criteria=criteria,
        files_touched=tuple(files),
        complexity=_COMPLEXITY_MAP.get(complexity, "M"),
        status=SpecStatus.ACTIVE,
    )
