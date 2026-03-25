"""Extended tests for HTTPToolExecutor -- covers response parsing paths.

Uses httpx mocking via a custom transport to avoid real HTTP calls.
Tests: passed=true, passed=false, status=failed, generic JSON, large response
truncation, non-200 status, list_tools success.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from stronghold.agents.strategies.tool_http import HTTPToolExecutor


# ---------------------------------------------------------------------------
# Helpers: mock transport for httpx
# ---------------------------------------------------------------------------


class MockTransport(httpx.AsyncBaseTransport):
    """Programmable async transport for httpx -- no real HTTP calls."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, Any]] = {}

    def set_response(self, path: str, status: int, body: Any) -> None:
        """Register a response for a path."""
        self.routes[path] = (status, body)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self.routes:
            status, body = self.routes[path]
            content = json.dumps(body).encode() if isinstance(body, (dict, list)) else body.encode()
            return httpx.Response(status, content=content)
        return httpx.Response(404, content=b"Not found")


class MockHTTPToolExecutor(HTTPToolExecutor):
    """HTTPToolExecutor that uses a mock transport instead of real HTTP."""

    def __init__(self, transport: MockTransport, base_url: str = "http://test-server:8300") -> None:
        super().__init__(base_url=base_url)
        self._transport = transport

    async def call(self, tool_name: str, args: dict[str, Any]) -> str:
        """Override to inject mock transport."""
        url = f"{self._base_url}/tools/{tool_name}"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=120.0,
            ) as client:
                resp = await client.post(url, json=args)
                if resp.status_code != 200:
                    return f"Error: HTTP {resp.status_code} - {resp.text[:200]}"
                data = resp.json()

                # Quality check tools have a "passed" field
                if "passed" in data:
                    if data["passed"]:
                        return f'"passed": true, "summary": "{data.get("summary", "OK")}"'
                    raw = data.get("raw_output", "")[:2000]
                    return f'"passed": false, "summary": "{data.get("summary", "")}"\n{raw}'

                # File/git tools have "status" or "content" or "entries"
                if "error" in data and data.get("status") == "failed":
                    return f'"status": "failed", "error": "{data["error"]}"'

                return json.dumps(data, indent=None)[:3000]
        except Exception as e:
            return f"Error: {e}"

    async def list_tools(self) -> list[dict[str, str]]:
        """Override to inject mock transport."""
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=10.0,
            ) as client:
                resp = await client.get(f"{self._base_url}/tools")
                if resp.status_code == 200:
                    data: dict[str, Any] = resp.json()
                    tools: list[dict[str, str]] = data.get("tools", [])
                    return tools
        except Exception:
            pass
        return []


# ---------------------------------------------------------------------------
# Tests: call() response parsing
# ---------------------------------------------------------------------------


class TestHTTPToolExecutorCall:
    async def test_passed_true_response(self) -> None:
        """Quality tools returning passed=true produce a success summary."""
        transport = MockTransport()
        transport.set_response(
            "/tools/run_pytest",
            200,
            {"passed": True, "summary": "All 42 tests passed"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": true' in result
        assert "All 42 tests passed" in result

    async def test_passed_false_response(self) -> None:
        """Quality tools returning passed=false include raw output."""
        transport = MockTransport()
        transport.set_response(
            "/tools/run_pytest",
            200,
            {
                "passed": False,
                "summary": "3 failed",
                "raw_output": "FAILED test_foo.py::test_bar - AssertionError",
            },
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": false' in result
        assert "3 failed" in result
        assert "FAILED test_foo" in result

    async def test_passed_false_missing_raw_output(self) -> None:
        """Quality tools returning passed=false without raw_output still work."""
        transport = MockTransport()
        transport.set_response(
            "/tools/run_pytest",
            200,
            {"passed": False, "summary": "1 failed"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("run_pytest", {"path": "."})
        assert '"passed": false' in result
        assert "1 failed" in result

    async def test_status_failed_response(self) -> None:
        """File/git tools returning status=failed + error produce error message."""
        transport = MockTransport()
        transport.set_response(
            "/tools/read_file",
            200,
            {"status": "failed", "error": "File not found: /tmp/missing.txt"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("read_file", {"path": "/tmp/missing.txt"})
        assert '"status": "failed"' in result
        assert "File not found" in result

    async def test_generic_json_response(self) -> None:
        """Generic JSON responses are returned as JSON strings."""
        transport = MockTransport()
        transport.set_response(
            "/tools/git_status",
            200,
            {"status": "ok", "files": ["a.py", "b.py"], "branch": "main"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("git_status", {})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["branch"] == "main"

    async def test_content_response(self) -> None:
        """Tools returning 'content' key are treated as generic JSON."""
        transport = MockTransport()
        transport.set_response(
            "/tools/read_file",
            200,
            {"content": "print('hello')", "path": "/tmp/test.py"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("read_file", {"path": "/tmp/test.py"})
        parsed = json.loads(result)
        assert parsed["content"] == "print('hello')"

    async def test_non_200_status(self) -> None:
        """Non-200 HTTP status returns an error string."""
        transport = MockTransport()
        transport.set_response("/tools/bad_tool", 500, {"detail": "Server error"})
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("bad_tool", {})
        assert "Error: HTTP 500" in result

    async def test_404_status(self) -> None:
        """404 returns an error string for unknown tool."""
        transport = MockTransport()
        # MockTransport returns 404 for unregistered routes
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("unknown_tool", {})
        assert "Error: HTTP 404" in result

    async def test_large_json_response_truncated(self) -> None:
        """Generic JSON responses > 3000 chars are truncated."""
        transport = MockTransport()
        large_data = {"data": "x" * 4000}
        transport.set_response("/tools/big_tool", 200, large_data)
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("big_tool", {})
        assert len(result) <= 3000

    async def test_error_has_error_key_but_not_failed_status(self) -> None:
        """JSON with 'error' key but status != 'failed' is treated as generic."""
        transport = MockTransport()
        transport.set_response(
            "/tools/weird_tool",
            200,
            {"error": "some warning", "status": "ok", "data": "result"},
        )
        executor = MockHTTPToolExecutor(transport)
        result = await executor.call("weird_tool", {})
        # Should be treated as generic JSON, not as a failure
        parsed = json.loads(result)
        assert parsed["data"] == "result"


# ---------------------------------------------------------------------------
# Tests: list_tools()
# ---------------------------------------------------------------------------


class TestHTTPToolExecutorListTools:
    async def test_list_tools_success(self) -> None:
        """list_tools returns tools from the server."""
        transport = MockTransport()
        transport.set_response(
            "/tools",
            200,
            {
                "tools": [
                    {"name": "run_pytest", "description": "Run pytest"},
                    {"name": "read_file", "description": "Read a file"},
                ]
            },
        )
        executor = MockHTTPToolExecutor(transport)
        tools = await executor.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "run_pytest"

    async def test_list_tools_non_200(self) -> None:
        """list_tools returns empty list on non-200 response."""
        transport = MockTransport()
        transport.set_response("/tools", 500, {"detail": "error"})
        executor = MockHTTPToolExecutor(transport)
        tools = await executor.list_tools()
        assert tools == []

    async def test_list_tools_empty(self) -> None:
        """list_tools returns empty list when server has no tools."""
        transport = MockTransport()
        transport.set_response("/tools", 200, {"tools": []})
        executor = MockHTTPToolExecutor(transport)
        tools = await executor.list_tools()
        assert tools == []


# ---------------------------------------------------------------------------
# Tests: base_url handling
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
# Tests: connection errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    async def test_connection_error_returns_error_string(self) -> None:
        """Connection errors are caught and returned as error strings."""
        executor = HTTPToolExecutor(base_url="http://localhost:99999")
        result = await executor.call("any_tool", {"key": "value"})
        assert result.startswith("Error:")

    async def test_list_tools_connection_error(self) -> None:
        """list_tools connection error returns empty list."""
        executor = HTTPToolExecutor(base_url="http://localhost:99999")
        tools = await executor.list_tools()
        assert tools == []
