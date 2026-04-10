"""Tests for the browser_fetch tool dispatch."""

from __future__ import annotations

import json

import httpx
import respx

from stronghold.tools.browser_fetch import (
    CAMOUFOX_URL,
    PLAYWRIGHT_URL,
    BrowserFetchExecutor,
)


@respx.mock
async def test_elite_routes_to_camoufox():
    executor = BrowserFetchExecutor()
    route = respx.post(f"{CAMOUFOX_URL}/fetch").mock(
        return_value=httpx.Response(200, json={"status": 200, "html": "<html>ok</html>", "final_url": "https://x.com"}),
    )
    result = await executor.execute(arguments={"url": "https://x.com"}, agent_name="ranger-elite")
    assert route.called
    assert result.success is True
    assert json.loads(result.content)["engine"] == "camoufox"


@respx.mock
async def test_ranger_routes_to_playwright():
    executor = BrowserFetchExecutor()
    route = respx.post(f"{PLAYWRIGHT_URL}/fetch").mock(
        return_value=httpx.Response(200, json={"status": 403, "html": "blocked", "final_url": "https://x.com"}),
    )
    result = await executor.execute(arguments={"url": "https://x.com"}, agent_name="ranger")
    assert route.called
    assert result.success is False
    assert json.loads(result.content)["engine"] == "playwright"


async def test_missing_url_returns_error():
    executor = BrowserFetchExecutor()
    result = await executor.execute(arguments={}, agent_name="ranger")
    assert result.success is False
    assert "url" in result.content.lower()


@respx.mock
async def test_backend_unreachable():
    executor = BrowserFetchExecutor()
    respx.post(f"{PLAYWRIGHT_URL}/fetch").mock(side_effect=httpx.ConnectError("refused"))
    result = await executor.execute(arguments={"url": "https://x.com"}, agent_name="ranger")
    assert result.success is False
    assert "unreachable" in result.content.lower()
