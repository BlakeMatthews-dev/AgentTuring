"""SearchReader (scaffold) — read-only search via SearXNG or compatible.

The operator provides a SearXNG (or compatible) JSON search endpoint.
Project Turing posts a query and returns the top results as a list of
(title, url, snippet) triples. Read-only: no posting, no clicks, no
side effects.

If your search lives behind something else (Brave, Bing, internal),
implement a class with the same `name = "search"` and `invoke(query)`
shape and register it instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.search")


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearxSearch:
    name = "search"
    mode = ToolMode.READ

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("SearxSearch requires base_url")
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=20.0)

    def invoke(
        self,
        *,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        params = {"q": query, "format": "json"}
        response = self._client.get(f"{self._base}/search", params=params)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        results = (data.get("results") or [])[:max_results]
        return [
            SearchResult(
                title=str(r.get("title") or ""),
                url=str(r.get("url") or ""),
                snippet=str(r.get("content") or ""),
            )
            for r in results
        ]
