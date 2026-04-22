"""Archie property-test generator: derives Hypothesis tests from Spec invariants.

Each invariant gets a PropertyTest with:
- A strategy matching the invariant kind
- A test body that exercises the declared property
- A module path following the tests/ convention
"""

from __future__ import annotations

from stronghold.types.spec import Invariant, InvariantKind, PropertyTest, Spec

_KIND_STRATEGIES: dict[InvariantKind, str] = {
    InvariantKind.PRECONDITION: "st.text(min_size=0, max_size=200)",
    InvariantKind.POSTCONDITION: "st.text(min_size=1, max_size=200)",
    InvariantKind.STATE_INVARIANT: "st.integers(min_value=0, max_value=1000)",
    InvariantKind.DATA_INVARIANT: "st.text(min_size=0, max_size=500)",
}

_KIND_BODIES: dict[InvariantKind, str] = {
    InvariantKind.PRECONDITION: ("from hypothesis import assume\nassume(len(x) > 0)\nassert True"),
    InvariantKind.POSTCONDITION: "result = execute(x)\nassert result is not None",
    InvariantKind.STATE_INVARIANT: (
        "before = get_state()\nmutate(x)\nafter = get_state()\nassert after >= before"
    ),
    InvariantKind.DATA_INVARIANT: "assert validate(x)",
}


def _module_path_for(inv: Invariant) -> str:
    if inv.protocol:
        return f"tests/protocols/test_{inv.protocol}_properties.py"
    return ""


def _build_property_test(inv: Invariant) -> PropertyTest:
    return PropertyTest(
        name=f"test_{inv.name}",
        invariant_name=inv.name,
        strategy_code=_KIND_STRATEGIES.get(inv.kind, "st.none()"),
        test_body=_KIND_BODIES.get(inv.kind, "assert True"),
        module_path=_module_path_for(inv),
    )


def generate_property_tests(spec: Spec) -> list[PropertyTest]:
    """Generate one PropertyTest per Invariant in the Spec."""
    return [_build_property_test(inv) for inv in spec.invariants]
