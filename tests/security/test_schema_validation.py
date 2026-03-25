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
