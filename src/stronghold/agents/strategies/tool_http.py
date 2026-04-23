"""HTTP tool executor: calls dev-tools-mcp and other HTTP-based tool servers."""

from __future__ import annotations

from typing import Any

import httpx


class HTTPToolExecutor:
    """Calls tools on HTTP servers like dev-tools-mcp."""

    def __init__(self, base_url: str = "http://dev-tools-mcp:8300") -> None:
        self._base_url = base_url.rstrip("/")

    async def call(self, tool_name: str, args: dict[str, Any]) -> str:
        """Call a tool by name with arguments.

        Handles two response formats:
        - Quality tools (run_pytest, etc.): {"passed": bool, "summary": str, "raw_output": str}
        - File tools (read_file, etc.): {"status": "ok", ...} or {"content": str, ...}
        """
        url = f"{self._base_url}/tools/{tool_name}"
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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

                # Return the JSON as-is for the LLM to parse
                import json

                return json.dumps(data, indent=None)[:3000]
        except Exception as e:
            return f"Error: {e}"

    async def list_tools(self) -> list[dict[str, str]]:
        """List available tools from the server."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/tools")
                if resp.status_code == 200:
                    data: dict[str, Any] = resp.json()
                    tools: list[dict[str, str]] = data.get("tools", [])
                    return tools
        except Exception:  # nosec B110 - remote MCP listing is optional; empty list is the fallback
            pass
        return []
