"""Sentinel schema validation + repair.

Validates tool_call arguments against the tool's declared JSON Schema.
Repairs common hallucination patterns: fuzzy enum match, type coercion, defaults.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any

from stronghold.types.security import SentinelVerdict, Violation


def validate_and_repair(
    args: dict[str, Any],
    schema: dict[str, Any],
) -> SentinelVerdict:
    """Validate args against JSON Schema. Attempt repair if invalid.

    Returns SentinelVerdict with allowed/repaired/violations.
    """
    violations: list[Violation] = []
    repaired = dict(args)
    was_repaired = False

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # Check required fields
    for field_name in required:
        if field_name not in args:
            field_schema = properties.get(field_name, {})
            if "default" in field_schema:
                repaired[field_name] = field_schema["default"]
                was_repaired = True
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="missing_required_with_default",
                        severity="info",
                        detail=f"Missing '{field_name}', used default",
                        repair_action=f"default={field_schema['default']}",
                    )
                )
            else:
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="missing_required",
                        severity="error",
                        detail=f"Required field '{field_name}' missing",
                    )
                )

    # Validate each provided field
    for field_name, value in list(repaired.items()):
        field_schema = properties.get(field_name)

        if field_schema is None:
            # Unknown field — try fuzzy match
            close = get_close_matches(field_name, properties.keys(), n=1, cutoff=0.6)
            if close:
                repaired[close[0]] = repaired.pop(field_name)
                was_repaired = True
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="field_name_fuzzy_match",
                        severity="warning",
                        detail=f"'{field_name}' → '{close[0]}'",
                        repair_action=f"renamed to {close[0]}",
                    )
                )
            continue

        # Enum validation + fuzzy match (preserves original enum type)
        if "enum" in field_schema and value not in field_schema["enum"]:
            enum_strs = [str(e) for e in field_schema["enum"]]
            close = get_close_matches(
                str(value),
                enum_strs,
                n=1,
                cutoff=0.6,
            )
            if close:
                # Restore original type from enum (not the string representation)
                matched_idx = enum_strs.index(close[0])
                repaired[field_name] = field_schema["enum"][matched_idx]
                was_repaired = True
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="enum_fuzzy_match",
                        severity="warning",
                        detail=f"'{value}' → '{close[0]}'",
                        repair_action=f"matched to {close[0]}",
                    )
                )
            else:
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="invalid_enum",
                        severity="error",
                        detail=f"'{value}' not in {field_schema['enum']}",
                    )
                )

        # Type coercion
        expected_type = field_schema.get("type")
        if expected_type and not _type_matches(value, expected_type):
            coerced = _try_coerce(value, expected_type)
            if coerced is not None:
                repaired[field_name] = coerced
                was_repaired = True
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="type_coercion",
                        severity="warning",
                        detail=f"Coerced {type(value).__name__} → {expected_type}",
                        repair_action=f"coerced to {expected_type}",
                    )
                )
            else:
                violations.append(
                    Violation(
                        boundary="system_to_tool",
                        rule="type_mismatch",
                        severity="error",
                        detail=f"Expected {expected_type}, got {type(value).__name__}",
                    )
                )

    # Determine verdict
    has_errors = any(v.severity == "error" for v in violations)
    if has_errors and not was_repaired:
        return SentinelVerdict(
            allowed=False,
            violations=tuple(violations),
        )

    return SentinelVerdict(
        allowed=True,
        repaired=was_repaired,
        repaired_data=repaired if was_repaired else None,
        violations=tuple(violations),
    )


def _type_matches(value: object, expected: str) -> bool:
    """Check if a value matches the expected JSON Schema type."""
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    return isinstance(value, type_map.get(expected, (object,)))


def _try_coerce(value: object, target_type: str) -> object | None:
    """Attempt to coerce a value to the target type."""
    try:
        if target_type == "string":
            return str(value)
        if target_type == "integer":
            return int(str(value))
        if target_type == "number":
            return float(str(value))
        if target_type == "boolean":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
    except (ValueError, TypeError):
        pass
    return None
