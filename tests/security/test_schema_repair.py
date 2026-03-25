"""Tests for Sentinel schema repair."""

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


class TestSchemaRepair:
    def test_fuzzy_enum_match(self) -> None:
        result = validate_and_repair(
            {"domain": "lights", "service": "turn_on", "entity_id": "x"},
            SCHEMA,
        )
        assert result.allowed
        assert result.repaired
        assert result.repaired_data["domain"] == "light"

    def test_field_name_fuzzy_match(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "service": {"type": "string"},
            },
            "required": ["entity_id"],
        }
        result = validate_and_repair(
            {"entityid": "fan.bedroom", "service": "turn_on"},
            schema,
        )
        # "entityid" should fuzzy match to "entity_id"
        assert result.repaired or result.allowed

    def test_unrepairable_returns_rejection(self) -> None:
        result = validate_and_repair({}, SCHEMA)
        assert not result.allowed


class TestTypeCoercion:
    def test_string_to_int(self) -> None:
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": []}
        result = validate_and_repair({"count": "5"}, schema)
        assert result.allowed
        if result.repaired:
            assert result.repaired_data["count"] == 5

    def test_int_to_string(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": []}
        result = validate_and_repair({"name": 42}, schema)
        assert result.allowed

    def test_bool_from_string_true(self) -> None:
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}, "required": []}
        result = validate_and_repair({"flag": "true"}, schema)
        assert result.allowed


class TestDefaultValues:
    def test_missing_required_with_default(self) -> None:
        schema = {
            "type": "object",
            "properties": {"mode": {"type": "string", "default": "auto"}},
            "required": ["mode"],
        }
        result = validate_and_repair({}, schema)
        assert result.allowed
        assert result.repaired
        assert result.repaired_data["mode"] == "auto"

    def test_missing_required_without_default_fails(self) -> None:
        schema = {
            "type": "object",
            "properties": {"mode": {"type": "string"}},
            "required": ["mode"],
        }
        result = validate_and_repair({}, schema)
        assert not result.allowed


class TestExtraFields:
    def test_unknown_field_ignored(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": []}
        result = validate_and_repair({"name": "test", "extra": "value"}, schema)
        assert result.allowed
