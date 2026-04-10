"""Browser fetch tool for Ranger and Ranger Elite.

Fetches web pages via server-side browser pods:
  - playwright-fetcher (vanilla Playwright, public tier)
  - camoufox-fetcher (Camoufox stealth Firefox, Elite tier only)

Engine selection is based on the calling agent's name, not a request param.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.browser_fetch")

PLAYWRIGHT_URL = os.environ.get(
    "BROWSER_FETCH_PLAYWRIGHT_URL",
    "http://playwright-fetcher.stronghold-platform.svc.cluster.local:8080",
)
CAMOUFOX_URL = os.environ.get(
    "BROWSER_FETCH_CAMOUFOX_URL",
    "http://camoufox-fetcher.stronghold-platform.svc.cluster.local:8080",
)
ELITE_AGENTS = frozenset(os.environ.get("BROWSER_FETCH_ELITE_AGENTS", "ranger-elite").split(","))
FETCH_TIMEOUT_SECONDS = 30.0

BROWSER_FETCH_TOOL_DEF = ToolDefinition(
    name="browser_fetch",
    description=(
        "Fetch a web page using a server-side browser. Returns the page's HTML "
        "and HTTP status. Works on sites that block simple HTTP clients."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "wait": {
                "type": "string",
                "description": "Page load strategy. Default: networkidle.",
                "enum": ["networkidle", "load", "domcontentloaded"],
                "default": "networkidle",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Page-load timeout in ms. Default: 15000.",
                "default": 15000,
            },
        },
        "required": ["url"],
    },
    groups=("search", "research"),
)


class BrowserFetchExecutor:
    """Dispatches to the correct fetcher pod based on agent identity."""

    async def execute(
        self,
        *,
        arguments: dict[str, Any] | None = None,
        agent_name: str = "",
        **_kwargs: Any,
    ) -> ToolResult:
        args = arguments or {}
        url = args.get("url", "")
        if not url:
            return ToolResult(content="Error: 'url' is required", success=False, error="missing_url")

        wait = args.get("wait", "networkidle")
        timeout_ms = args.get("timeout_ms", 15000)

        if agent_name in ELITE_AGENTS:
            backend_url = CAMOUFOX_URL
            engine = "camoufox"
        else:
            backend_url = PLAYWRIGHT_URL
            engine = "playwright"

        logger.info("browser_fetch: agent=%s engine=%s url=%s", agent_name, engine, url)

        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{backend_url}/fetch",
                    json={"url": url, "wait": wait, "timeout_ms": timeout_ms},
                )
                data = resp.json()
        except httpx.ConnectError as e:
            msg = f"Browser fetch backend ({engine}) unreachable: {e}"
            logger.error(msg)
            return ToolResult(content=msg, success=False, error="backend_unreachable")
        except Exception as e:
            msg = f"Browser fetch error: {e}"
            logger.error(msg)
            return ToolResult(content=msg, success=False, error=str(type(e).__name__))

        status = data.get("status", 0)
        html = data.get("html", "")
        final_url = data.get("final_url", url)

        result_payload: dict[str, Any] = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "html_length": len(html),
            "engine": engine,
        }

        if status and 200 <= status < 300:
            max_chars = 50000
            truncated = html[:max_chars]
            if len(html) > max_chars:
                truncated += f"\n\n[... truncated {len(html) - max_chars} chars ...]"
            result_payload["html"] = truncated
            return ToolResult(content=json.dumps(result_payload), success=True)
        else:
            result_payload["error"] = f"upstream returned HTTP {status}"
            return ToolResult(
                content=json.dumps(result_payload),
                success=False,
                error=f"upstream_http_{status}",
            )
