"""z.ai provider client (OpenAI-compatible API surface).

z.ai exposes an OpenAI-compatible chat-completions endpoint. Free tier
operates on a rolling 5-hour usage window — different window shape from
Gemini's RPM, which stresses the FreeTierQuotaTracker's pressure math in
a different way.

If z.ai's actual request/response shape differs from what's assumed here,
the two places to update are the POST body and `_extract_text`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .base import (
    FreeTierWindow,
    ProviderUnavailable,
    RateLimited,
)


logger = logging.getLogger("turing.providers.zai")


DEFAULT_BASE_URL: str = "https://api.z.ai/api/paas/v4"
DEFAULT_MODEL: str = "glm-4-flash"
DEFAULT_WINDOW_DURATION: timedelta = timedelta(hours=5)
DEFAULT_TOKENS_ALLOWED_PER_WINDOW: int = 5_000_000


class ZaiProvider:
    name: str = "zai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        window_duration: timedelta = DEFAULT_WINDOW_DURATION,
        tokens_allowed_per_window: int = DEFAULT_TOKENS_ALLOWED_PER_WINDOW,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ZaiProvider requires a non-empty api_key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._window_duration = window_duration
        self._tokens_allowed = tokens_allowed_per_window
        self._client = client or httpx.Client(timeout=30.0)
        self._window_started_at: datetime = datetime.now(UTC)
        self._tokens_used: int = 0

    def complete(self, prompt: str, *, max_tokens: int = 512) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.8,
        }
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"zai request error: {exc}") from exc

        if response.status_code == 429:
            raise RateLimited("zai returned 429")
        if 500 <= response.status_code < 600:
            try:
                retry = self._client.post(url, headers=headers, json=body)
            except httpx.RequestError as exc:
                raise ProviderUnavailable(f"zai retry error: {exc}") from exc
            if not retry.is_success:
                raise ProviderUnavailable(
                    f"zai {retry.status_code}: {retry.text[:200]}"
                )
            response = retry
        if not response.is_success:
            raise ProviderUnavailable(
                f"zai {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        text = _extract_text(data)
        self._record_usage(prompt, text, max_tokens)
        return text

    def quota_window(self) -> FreeTierWindow | None:
        now = datetime.now(UTC)
        if now - self._window_started_at >= self._window_duration:
            self._window_started_at = now
            self._tokens_used = 0
        return FreeTierWindow(
            provider=self.name,
            window_kind="rolling_hours",
            window_started_at=self._window_started_at,
            window_duration=self._window_duration,
            tokens_allowed=self._tokens_allowed,
            tokens_used=self._tokens_used,
        )

    def _record_usage(self, prompt: str, reply: str, max_tokens: int) -> None:
        self._tokens_used += (len(prompt) + len(reply)) // 4

    def close(self) -> None:
        self._client.close()


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""
