"""MediaWiki writer (scaffold).

Posts to a MediaWiki instance via api.php (action=edit). Operator provides
the wiki URL + a bot password (https://www.mediawiki.org/wiki/Manual:Bot_passwords).
The bot user must have edit permission on the target namespace.

Real client; Project Turing has no way to verify the operator's wiki shape,
so the page-naming convention is configurable (default: `Turing/<title>`).

If your wiki isn't MediaWiki, swap this for a class with the same `invoke()`
signature and register it as `wiki_writer`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.wiki")


class MediaWikiWriter:
    name = "wiki_writer"
    mode = ToolMode.WRITE

    def __init__(
        self,
        *,
        api_url: str,
        bot_username: str,
        bot_password: str,
        page_prefix: str = "Turing/",
        client: httpx.Client | None = None,
    ) -> None:
        if not (api_url and bot_username and bot_password):
            raise ValueError("MediaWikiWriter requires api_url, bot_username, bot_password")
        self._api_url = api_url
        self._username = bot_username
        self._password = bot_password
        self._page_prefix = page_prefix
        self._client = client or httpx.Client(timeout=30.0)
        self._logged_in = False
        self._csrf_token: str | None = None

    def invoke(
        self,
        *,
        title: str,
        content: str,
        summary: str = "via Project Turing",
        section: str | None = None,
    ) -> dict[str, Any]:
        if not self._logged_in:
            self._login()
        if self._csrf_token is None:
            self._fetch_csrf()
        params: dict[str, Any] = {
            "action": "edit",
            "format": "json",
            "title": f"{self._page_prefix}{title}",
            "text": content,
            "summary": summary,
            "token": self._csrf_token,
            "bot": "1",
        }
        if section is not None:
            params["section"] = section
        response = self._client.post(self._api_url, data=params)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"wiki edit error: {body['error']}")
        return body.get("edit", {})

    def _login(self) -> None:
        token_resp = self._client.get(
            self._api_url,
            params={
                "action": "query",
                "meta": "tokens",
                "type": "login",
                "format": "json",
            },
        )
        token = token_resp.json()["query"]["tokens"]["logintoken"]
        login_resp = self._client.post(
            self._api_url,
            data={
                "action": "login",
                "lgname": self._username,
                "lgpassword": self._password,
                "lgtoken": token,
                "format": "json",
            },
        )
        result = login_resp.json().get("login", {})
        if result.get("result") != "Success":
            raise RuntimeError(f"wiki login failed: {result}")
        self._logged_in = True

    def _fetch_csrf(self) -> None:
        resp = self._client.get(
            self._api_url,
            params={
                "action": "query",
                "meta": "tokens",
                "format": "json",
            },
        )
        self._csrf_token = resp.json()["query"]["tokens"]["csrftoken"]
