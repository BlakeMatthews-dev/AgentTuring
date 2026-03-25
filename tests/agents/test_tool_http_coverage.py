"""Tests for HTTPToolExecutor: covers call() success paths and list_tools()."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from stronghold.agents.strategies.tool_http import HTTPToolExecutor


class TestCallSuccess:
    """Test the call() success path with various response formats."""

    @respx.mock
    async def test_passed_true_response(self) -> None:
        respx.post("http://fake:8300/tools/run_pytest").mock(
            return_value=httpx.Response(200, json={"passed": True, "summary": "All tests passed"})
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("run_pytest", {"path": "tests/"})
        assert '"passed": true' in result
        assert "All tests passed" in result

    @respx.mock
    async def test_passed_false_response(self) -> None:
        respx.post("http://fake:8300/tools/run_pytest").mock(
            return_value=httpx.Response(200, json={
                "passed": False, "summary": "2 failed", "raw_output": "FAIL test_x\nFAIL test_y"
            })
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("run_pytest", {})
        assert '"passed": false' in result
        assert "2 failed" in result
        assert "FAIL test_x" in result

    @respx.mock
    async def test_file_tool_json_response(self) -> None:
        respx.post("http://fake:8300/tools/read_file").mock(
            return_value=httpx.Response(200, json={"status": "ok", "content": "file contents here"})
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("read_file", {"path": "main.py"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["content"] == "file contents here"

    @respx.mock
    async def test_failed_status_response(self) -> None:
        respx.post("http://fake:8300/tools/write_file").mock(
            return_value=httpx.Response(200, json={"status": "failed", "error": "Permission denied"})
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("write_file", {})
        assert '"status": "failed"' in result
        assert "Permission denied" in result

    @respx.mock
    async def test_non_200_returns_error(self) -> None:
        respx.post("http://fake:8300/tools/bad").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("bad", {})
        assert result.startswith("Error: HTTP 500")

    async def test_connection_error_returns_error(self) -> None:
        executor = HTTPToolExecutor(base_url="http://127.0.0.1:1")
        result = await executor.call("test", {})
        assert result.startswith("Error:")

    @respx.mock
    async def test_large_output_truncated(self) -> None:
        respx.post("http://fake:8300/tools/big").mock(
            return_value=httpx.Response(200, json={"data": "x" * 5000})
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.call("big", {})
        assert len(result) <= 3000


class TestListToolsSuccess:
    """Test list_tools() success path."""

    @respx.mock
    async def test_returns_parsed_tools(self) -> None:
        respx.get("http://fake:8300/tools").mock(
            return_value=httpx.Response(200, json={"tools": [
                {"name": "read_file", "description": "Read a file"},
                {"name": "run_pytest", "description": "Run tests"},
            ]})
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        tools = await executor.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "read_file"
        assert tools[1]["name"] == "run_pytest"

    async def test_connection_error_returns_empty(self) -> None:
        executor = HTTPToolExecutor(base_url="http://127.0.0.1:1")
        result = await executor.list_tools()
        assert result == []

    @respx.mock
    async def test_non_200_returns_empty(self) -> None:
        respx.get("http://fake:8300/tools").mock(
            return_value=httpx.Response(500, text="down")
        )
        executor = HTTPToolExecutor(base_url="http://fake:8300")
        result = await executor.list_tools()
        assert result == []


class TestBaseUrlHandling:
    def test_trailing_slash_stripped(self) -> None:
        executor = HTTPToolExecutor(base_url="http://localhost:8300/")
        assert executor._base_url == "http://localhost:8300"

    def test_no_trailing_slash(self) -> None:
        executor = HTTPToolExecutor(base_url="http://localhost:8300")
        assert executor._base_url == "http://localhost:8300"
