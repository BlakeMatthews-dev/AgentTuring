"""Tests for tool dispatcher: routing, timeout, HTTP fallback."""

import pytest

from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.types.tool import ToolDefinition, ToolResult


class TestBasicDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_executor(self) -> None:
        reg = InMemoryToolRegistry()

        async def echo(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content=f"echo: {args.get('msg', '')}")

        reg.register(ToolDefinition(name="echo", description="echo"), executor=echo)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("echo", {"msg": "hello"})
        assert result == "echo: hello"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        reg = InMemoryToolRegistry()
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("nonexistent", {})
        assert "not registered" in result

    @pytest.mark.asyncio
    async def test_executor_error_returns_error_string(self) -> None:
        reg = InMemoryToolRegistry()

        async def failing(args: dict) -> ToolResult:  # type: ignore[type-arg]
            msg = "boom"
            raise RuntimeError(msg)

        reg.register(ToolDefinition(name="fail", description="fail"), executor=failing)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("fail", {})
        assert "Error" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_executor_returning_error_result(self) -> None:
        reg = InMemoryToolRegistry()

        async def err(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content="", success=False, error="bad input")

        reg.register(ToolDefinition(name="err", description="err"), executor=err)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("err", {})
        assert "bad input" in result


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self) -> None:
        import asyncio

        reg = InMemoryToolRegistry()

        async def slow(args: dict) -> ToolResult:  # type: ignore[type-arg]
            await asyncio.sleep(10)
            return ToolResult(content="done")

        reg.register(ToolDefinition(name="slow", description="slow"), executor=slow)
        dispatcher = ToolDispatcher(reg, default_timeout=0.1)
        result = await dispatcher.execute("slow", {})
        assert "timed out" in result


class TestHTTPFallback:
    @pytest.mark.asyncio
    async def test_tool_with_endpoint_uses_http(self) -> None:
        """Tool with endpoint but no executor should try HTTP (will fail in test)."""
        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(
                name="remote",
                description="remote tool",
                endpoint="http://localhost:99999/nonexistent",
            )
        )
        dispatcher = ToolDispatcher(reg, default_timeout=2.0)
        result = await dispatcher.execute("remote", {"q": "test"})
        assert "Error" in result  # HTTP will fail (no server)
