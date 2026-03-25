"""Tests for tool types and definitions."""

from stronghold.types.tool import ToolCall, ToolDefinition, ToolResult


class TestToolDefinition:
    def test_create_basic_tool(self) -> None:
        tool = ToolDefinition(name="test_tool", description="A test tool")
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"

    def test_tool_with_parameters(self) -> None:
        tool = ToolDefinition(
            name="ha_control",
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "service": {"type": "string"},
                },
                "required": ["entity_id", "service"],
            },
        )
        assert "entity_id" in tool.parameters["properties"]

    def test_tool_with_groups(self) -> None:
        tool = ToolDefinition(name="ha_control", groups=("automation", "general"))
        assert "automation" in tool.groups


class TestToolCall:
    def test_create_tool_call(self) -> None:
        tc = ToolCall(id="tc1", name="ha_control", arguments={"entity_id": "fan.bedroom"})
        assert tc.id == "tc1"
        assert tc.arguments["entity_id"] == "fan.bedroom"


class TestToolResult:
    def test_success_result(self) -> None:
        result = ToolResult(content="OK", success=True)
        assert result.success

    def test_error_result(self) -> None:
        result = ToolResult(content="", success=False, error="Not found")
        assert not result.success
        assert result.error == "Not found"

    def test_warden_flags(self) -> None:
        result = ToolResult(content="data", warden_flags=("suspicious_content",))
        assert len(result.warden_flags) == 1
