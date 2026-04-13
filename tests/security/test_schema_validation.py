"""Tests for Sentinel schema validation."""

from stronghold.security.sentinel.validator import validate_and_repair

SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": ["light", "switch", "fan"]},
        "service": {"type": "string"},
        "entity_id": {"type": "string"},
    },
    "required": ["domain", "service", "entity_id"],
}


class TestSchemaValidation:
    def test_valid_args_pass(self) -> None:
        result = validate_and_repair(
            {"domain": "fan", "service": "turn_on", "entity_id": "fan.bedroom"},
            SCHEMA,
        )
        assert result.allowed
        assert not result.repaired

    def test_missing_required_rejected(self) -> None:
        result = validate_and_repair(
            {"domain": "fan"},
            SCHEMA,
        )
        assert not result.allowed

    def test_wrong_enum_rejected_without_close_match(self) -> None:
        result = validate_and_repair(
            {"domain": "microwave", "service": "turn_on", "entity_id": "x"},
            SCHEMA,
        )
        # "microwave" is not close to any enum value
        has_error = any(v.severity == "error" for v in result.violations)
        assert has_error


class TestFailOpenBug:
    """H11: Schema validation must not fail open when repair fixes one field
    but other errors remain unresolved."""

    def test_repair_on_one_field_does_not_suppress_other_errors(self) -> None:
        """Fuzzy-matching 'lights' -> 'light' repairs enum, but entity_id is
        still missing and has no default. Result must be rejected."""
        result = validate_and_repair(
            {"domain": "lights", "service": "turn_on"},
            SCHEMA,
        )
        # entity_id is required, missing, no default -> must reject
        assert not result.allowed, "Repair on 'domain' must not suppress missing 'entity_id' error"

    def test_multiple_errors_all_reported(self) -> None:
        """When multiple fields have errors, ALL must appear in violations."""
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["auto", "manual"]},
                "count": {"type": "integer"},
                "name": {"type": "string"},
            },
            "required": ["mode", "count", "name"],
        }
        result = validate_and_repair(
            {"mode": "xxxxx", "count": "not_a_number"},
            schema,
        )
        assert not result.allowed
        error_rules = [v.rule for v in result.violations if v.severity == "error"]
        # Must report: invalid_enum for mode, type_mismatch for count, missing_required for name
        assert "missing_required" in error_rules
        assert len(error_rules) >= 2, f"Expected multiple errors, got: {error_rules}"

    def test_single_field_repair_does_not_mask_type_error(self) -> None:
        """Repairing an enum must not prevent a type mismatch from being flagged."""
        schema = {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "enum": ["light", "switch"]},
                "brightness": {"type": "integer"},
            },
            "required": ["domain", "brightness"],
        }
        result = validate_and_repair(
            {"domain": "lights", "brightness": [1, 2, 3]},
            schema,
        )
        assert not result.allowed, (
            "Repairing 'domain' enum must not suppress type error on 'brightness'"
        )
