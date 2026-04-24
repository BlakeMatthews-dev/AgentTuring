"""GitHub REST client used by every github/* playbook.

Thin wrapper around httpx.AsyncClient with GitHub-specific headers and
the bot-installation-token dance. Shared so the playbooks do not each
re-implement auth/pagination.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from stronghold.tools.github import _get_app_installation_token

logger = logging.getLogger("stronghold.playbooks.github.client")

DEFAULT_TIMEOUT = 30.0
_PR_URL_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_ISSUE_URL_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)")


@dataclass(frozen=True)
class PullRequestRef:
    owner: str
    repo: str
    number: int


@dataclass(frozen=True)
class IssueRef:
    owner: str
    repo: str
    number: int


def parse_pr_url(url: str) -> PullRequestRef:
    m = _PR_URL_RE.match(url)
    if not m:
        raise ValueError(f"Not a GitHub PR URL: {url}")
    return PullRequestRef(owner=m.group(1), repo=m.group(2), number=int(m.group(3)))


def parse_issue_url(url: str) -> IssueRef:
    m = _ISSUE_URL_RE.match(url)
    if not m:
        raise ValueError(f"Not a GitHub issue URL: {url}")
    return IssueRef(owner=m.group(1), repo=m.group(2), number=int(m.group(3)))


class GitHubClient:
    """Minimal GitHub REST client for playbooks.

    Not a full SDK — playbooks should call the specific helpers they need
    and fall back to `request()` for one-offs.
    """

    def __init__(
        self,
        token: str = "",
        *,
        bot: str = "gatekeeper",
        base_url: str = "https://api.github.com",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        import os  # noqa: PLC0415

        app_token = _get_app_installation_token(bot)
        self._token = app_token or token or os.environ.get("GITHUB_TOKEN", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self, *, media_type: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": media_type,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        media_type: str = "application/vnd.github+json",
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(media_type=media_type),
                params=params,
                json=json_body,
            )
        return resp

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        resp = await self.request("GET", path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_text(self, path: str, *, media_type: str) -> str:
        resp = await self.request("GET", path, media_type=media_type)
        resp.raise_for_status()
        return resp.text
