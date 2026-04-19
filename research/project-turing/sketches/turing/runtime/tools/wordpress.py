"""WordPress writer (scaffold).

Posts to a WordPress site via the REST API
(https://developer.wordpress.org/rest-api/reference/posts/). Operator
provides the site URL + a user + an Application Password (Settings → Users
→ your user → Application Passwords). Posts default to draft status so a
human can review before publishing — flip `status="publish"` if you want
auto-publish.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.wordpress")


class WordPressWriter:
    name = "wordpress_writer"
    mode = ToolMode.WRITE

    def __init__(
        self,
        *,
        site_url: str,
        username: str,
        application_password: str,
        default_status: str = "draft",
        client: httpx.Client | None = None,
    ) -> None:
        if not (site_url and username and application_password):
            raise ValueError(
                "WordPressWriter requires site_url, username, application_password"
            )
        self._site = site_url.rstrip("/")
        self._auth = (username, application_password)
        self._default_status = default_status
        self._client = client or httpx.Client(timeout=30.0)

    def invoke(
        self,
        *,
        title: str,
        content: str,
        status: str | None = None,
        categories: list[int] | None = None,
        tags: list[int] | None = None,
        excerpt: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._site}/wp-json/wp/v2/posts"
        body: dict[str, Any] = {
            "title": title,
            "content": content,
            "status": status or self._default_status,
        }
        if categories:
            body["categories"] = categories
        if tags:
            body["tags"] = tags
        if excerpt:
            body["excerpt"] = excerpt
        response = self._client.post(url, json=body, auth=self._auth)
        response.raise_for_status()
        return response.json()
