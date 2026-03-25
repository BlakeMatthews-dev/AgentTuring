"""Tests for tool registry: registration, lookup, OpenAI schema generation."""

from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.types.tool import ToolDefinition


def _make_tool(
    name: str = "test_tool",
    groups: tuple[str, ...] = ("general",),
    **kwargs: object,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=str(kwargs.get("description", f"A {name} tool")),
        groups=groups,
    )


class TestRegistration:
    def test_register_and_get(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("alpha"))
        assert reg.get("alpha") is not None
        assert reg.get("alpha").name == "alpha"  # type: ignore[union-attr]

    def test_get_nonexistent(self) -> None:
        reg = InMemoryToolRegistry()
        assert reg.get("nope") is None

    def test_len(self) -> None:
        reg = InMemoryToolRegistry()
        assert len(reg) == 0
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg) == 2

    def test_contains(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("x"))
        assert "x" in reg
        assert "y" not in reg

    def test_list_all(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg.list_all()) == 2


class TestTaskTypeFiltering:
    def test_list_for_task(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("ha", groups=("automation",)))
        reg.register(_make_tool("search", groups=("search",)))
        reg.register(_make_tool("general", groups=("general", "automation")))
        auto = reg.list_for_task("automation")
        assert len(auto) == 2
        assert {t.name for t in auto} == {"ha", "general"}

    def test_no_groups_matches_all(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("universal", groups=()))
        assert len(reg.list_for_task("anything")) == 1

    def test_agent_tools_filter(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        reg.register(_make_tool("c"))
        defs = reg.get_definitions(agent_tools=("a", "c"))
        assert len(defs) == 2
        assert {d.name for d in defs} == {"a", "c"}


class TestOpenAISchemas:
    def test_generates_function_format(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(
                name="weather",
                description="Get weather",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            )
        )
        schemas = reg.to_openai_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "weather"
        assert "city" in schemas[0]["function"]["parameters"]["properties"]

    def test_task_type_filters_schemas(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("ha", groups=("automation",)))
        reg.register(_make_tool("search", groups=("search",)))
        schemas = reg.to_openai_schemas(task_type="automation")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "ha"


class TestExecutorRegistration:
    def test_register_with_executor(self) -> None:
        reg = InMemoryToolRegistry()

        async def my_exec(args: dict) -> object:
            return None

        reg.register(_make_tool("custom"), executor=my_exec)
        assert reg.get_executor("custom") is not None

    def test_no_executor_returns_none(self) -> None:
        reg = InMemoryToolRegistry()
        reg.register(_make_tool("no_exec"))
        assert reg.get_executor("no_exec") is None
