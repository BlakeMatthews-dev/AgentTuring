"""Tests for HTTP tool executor."""

import pytest

from stronghold.agents.strategies.tool_http import HTTPToolExecutor


class TestHTTPToolExecutor:
    @pytest.mark.asyncio
    async def test_unreachable_server_returns_error(self) -> None:
        executor = HTTPToolExecutor(base_url="http://localhost:99999")
        result = await executor.call("run_pytest", {"path": "."})
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_tools_unreachable(self) -> None:
        executor = HTTPToolExecutor(base_url="http://localhost:99999")
        tools = await executor.list_tools()
        assert tools == []
