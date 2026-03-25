"""Tests for skill types."""

from stronghold.types.skill import SkillDefinition, SkillMetadata


class TestSkillDefinition:
    def test_create_skill(self) -> None:
        skill = SkillDefinition(
            name="weather",
            description="Get current weather",
            groups=("general",),
            system_prompt="Check weather for the given location.",
        )
        assert skill.name == "weather"
        assert skill.trust_tier == "t2"

    def test_skill_with_parameters(self) -> None:
        skill = SkillDefinition(
            name="dns_check",
            parameters={"type": "object", "properties": {"domain": {"type": "string"}}},
        )
        assert "domain" in skill.parameters["properties"]


class TestSkillMetadata:
    def test_create_metadata(self) -> None:
        meta = SkillMetadata(
            name="weather",
            description="Weather lookup",
            source_url="https://example.com/weather-skill",
            author="test",
        )
        assert meta.name == "weather"
