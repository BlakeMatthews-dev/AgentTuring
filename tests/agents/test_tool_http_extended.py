"""Extended tests for HTTPToolExecutor — response parsing paths.

Previous version of this file subclassed ``HTTPToolExecutor`` and reimplemented
``call()`` / ``list_tools()`` verbatim, so every test exercised the *copy* rather
than the production code. This rewrite drops the subclass and uses ``respx`` to
mock the remote MCP server at the transport layer — the real production
``HTTPToolExecutor.call()`` / ``.list_tools()`` methods run unchanged.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from stronghold.agents.strategies.tool_http import HTTPToolExecutor

BASE_URL = "http://test-server:8300"


def _tool(name: str) -> str:
    return f"{BASE_URL}/tools/{name}"


# ---------------------------------------------------------------------------
# Tests: call() response parsing
# ---------------------------------------------------------------------------


class TestHTTPToolExecutorCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_passed_true_response(self) -> None:
        """Quality tools returning passed=true produce a success summary."""
        respx.post(_tool("run_pytest")).mock(
            return_value=httpx.Response(
                200,
                json={"passed": True, "summary": "All 42 tests passed"},
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": true' in result
        assert "All 42 tests passed" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_passed_false_response(self) -> None:
        """Quality tools returning passed=false include raw output."""
        respx.post(_tool("run_pytest")).mock(
            return_value=httpx.Response(
                200,
                json={
                    "passed": False,
                    "summary": "3 failed",
                    "raw_output": "FAILED test_foo.py::test_bar - AssertionError",
                },
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": false' in result
        assert "3 failed" in result
        assert "FAILED test_foo" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_passed_false_missing_raw_output(self) -> None:
        """passed=false without raw_output still works."""
        respx.post(_tool("run_pytest")).mock(
            return_value=httpx.Response(
                200, json={"passed": False, "summary": "1 failed"}
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": false' in result
        assert "1 failed" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_status_failed_response(self) -> None:
        """File/git tools returning status=failed + error produce error message."""
        respx.post(_tool("read_file")).mock(
            return_value=httpx.Response(
                200,
                json={"status": "failed", "error": "File not found: /tmp/missing.txt"},
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("read_file", {"path": "/tmp/missing.txt"})
        assert '"status": "failed"' in result
        assert "File not found" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_generic_json_response(self) -> None:
        """Generic JSON responses are returned as JSON strings."""
        route = respx.post(_tool("git_status")).mock(
            return_value=httpx.Response(
                200,
                json={"status": "ok", "files": ["a.py", "b.py"], "branch": "main"},
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("git_status", {})
        # Verify the real client actually POSTed our args to the right URL.
        assert route.called
        assert route.calls.last.request.method == "POST"
        assert route.calls.last.request.url == _tool("git_status")

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["branch"] == "main"

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_sends_args_as_json_body(self) -> None:
        """POST body is the args dict serialised as JSON."""
        route = respx.post(_tool("echo_tool")).mock(
            return_value=httpx.Response(200, json={"echo": "ok"})
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        await executor.call("echo_tool", {"key": "value", "n": 7})

        assert route.called
        body = json.loads(route.calls.last.request.content)
        assert body == {"key": "value", "n": 7}

    @pytest.mark.asyncio
    @respx.mock
    async def test_content_response(self) -> None:
        """Tools returning 'content' key are treated as generic JSON."""
        respx.post(_tool("read_file")).mock(
            return_value=httpx.Response(
                200, json={"content": "print('hello')", "path": "/tmp/test.py"}
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("read_file", {"path": "/tmp/test.py"})
        parsed = json.loads(result)
        assert parsed["content"] == "print('hello')"

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_200_status(self) -> None:
        """Non-200 HTTP status returns an error string."""
        respx.post(_tool("bad_tool")).mock(
            return_value=httpx.Response(500, json={"detail": "Server error"})
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("bad_tool", {})
        assert "Error: HTTP 500" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_status(self) -> None:
        """404 returns an error string for unknown tool."""
        respx.post(_tool("unknown_tool")).mock(
            return_value=httpx.Response(404, content=b"Not found")
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("unknown_tool", {})
        assert "Error: HTTP 404" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_large_json_response_truncated(self) -> None:
        """Generic JSON responses > 3000 chars are truncated."""
        respx.post(_tool("big_tool")).mock(
            return_value=httpx.Response(200, json={"data": "x" * 4000})
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("big_tool", {})
        assert len(result) <= 3000

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_has_error_key_but_not_failed_status(self) -> None:
        """JSON with 'error' key but status != 'failed' is treated as generic."""
        respx.post(_tool("weird_tool")).mock(
            return_value=httpx.Response(
                200,
                json={"error": "some warning", "status": "ok", "data": "result"},
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("weird_tool", {})
        # Should be treated as generic JSON, not as a failure.
        parsed = json.loads(result)
        assert parsed["data"] == "result"


# ---------------------------------------------------------------------------
# Tests: list_tools()
# ---------------------------------------------------------------------------


class TestHTTPToolExecutorListTools:
    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools_success(self) -> None:
        """list_tools returns tools from the server."""
        route = respx.get(f"{BASE_URL}/tools").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tools": [
                        {"name": "run_pytest", "description": "Run pytest"},
                        {"name": "read_file", "description": "Read a file"},
                    ]
                },
            )
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        tools = await executor.list_tools()

        assert route.called
        assert route.calls.last.request.method == "GET"
        assert len(tools) == 2
        assert tools[0]["name"] == "run_pytest"

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools_non_200(self) -> None:
        """list_tools returns empty list on non-200 response."""
        respx.get(f"{BASE_URL}/tools").mock(
            return_value=httpx.Response(500, json={"detail": "error"})
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        tools = await executor.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools_empty(self) -> None:
        """list_tools returns empty list when server has no tools."""
        respx.get(f"{BASE_URL}/tools").mock(
            return_value=httpx.Response(200, json={"tools": []})
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        tools = await executor.list_tools()
        assert tools == []


# ---------------------------------------------------------------------------
# Tests: base_url handling (no HTTP)
# ---------------------------------------------------------------------------


class TestBaseURL:
    def test_trailing_slash_stripped(self) -> None:
        """Trailing slash on base_url is stripped."""
        executor = HTTPToolExecutor(base_url="http://localhost:8300/")
        assert not executor._base_url.endswith("/")

    def test_default_base_url(self) -> None:
        """Default base_url is dev-tools-mcp:8300."""
        executor = HTTPToolExecutor()
        assert "dev-tools-mcp" in executor._base_url
        assert "8300" in executor._base_url


# ---------------------------------------------------------------------------
# Tests: connection errors — exercise real httpx exception propagation.
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error_returns_error_string(self) -> None:
        """Connection errors are caught and returned as error strings."""
        respx.post(_tool("any_tool")).mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        result = await executor.call("any_tool", {"key": "value"})
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_tools_connection_error(self) -> None:
        """list_tools connection error returns empty list."""
        respx.get(f"{BASE_URL}/tools").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        executor = HTTPToolExecutor(base_url=BASE_URL)
        tools = await executor.list_tools()
        assert tools == []
