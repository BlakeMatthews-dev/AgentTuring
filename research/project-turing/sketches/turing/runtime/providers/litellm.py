"""LiteLLM-backed Provider — single client, many pools.

The operator runs LiteLLM with their providers (Google, z.ai, OpenRouter, …)
already configured. Project Turing connects with a single virtual key and
routes by model name. One LiteLLMProvider per pool: the pool's `model`
field tells LiteLLM which backend to invoke.

LiteLLM exposes an OpenAI-compatible `/chat/completions` endpoint, so the
request shape is the same regardless of which underlying provider serves
the model.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..pools import PoolConfig
from .base import (
    FreeTierWindow,
    ProviderUnavailable,
    RateLimited,
)


logger = logging.getLogger("turing.providers.litellm")


class LiteLLMProvider:
    """One pool's worth of LiteLLM access."""

    def __init__(
        self,
        *,
        pool_config: PoolConfig,
        base_url: str,
        virtual_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not virtual_key:
            raise ValueError("LiteLLMProvider requires a non-empty virtual_key")
        if not base_url:
            raise ValueError("LiteLLMProvider requires a non-empty base_url")
        self._pool_config = pool_config
        self.name = pool_config.pool_name
        self._model = pool_config.model
        self._base_url = base_url.rstrip("/")
        self._virtual_key = virtual_key
        self._client = client or httpx.Client(timeout=30.0)

        self._window_started_at: datetime = datetime.now(UTC)
        self._window_duration: timedelta = timedelta(seconds=pool_config.window_duration_seconds)
        self._tokens_allowed: int = pool_config.tokens_allowed
        self._tokens_used: int = 0

    def complete(self, prompt: str, *, max_tokens: int | None = None) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"litellm[{self._model}] request error: {exc}") from exc

        if response.status_code == 429:
            raise RateLimited(f"litellm[{self._model}] returned 429")
        if 500 <= response.status_code < 600:
            try:
                retry = self._client.post(url, headers=headers, json=body)
            except httpx.RequestError as exc:
                raise ProviderUnavailable(f"litellm[{self._model}] retry error: {exc}") from exc
            if not retry.is_success:
                raise ProviderUnavailable(
                    f"litellm[{self._model}] {retry.status_code}: <response body sanitized>"
                )
            response = retry
        if not response.is_success:
            raise ProviderUnavailable(
                f"litellm[{self._model}] {response.status_code}: <response body sanitized>"
            )

        data = response.json()
        text = _extract_text(data)
        usage = data.get("usage") or {}
        tokens_used = (
            int(usage.get("total_tokens", 0)) or (len(prompt) + len(text)) // 4  # fallback estimate
        )
        self._tokens_used += tokens_used
        return text

    def embed(self, text: str) -> list[float]:
        """Call LiteLLM /v1/embeddings. Uses this pool's model.

        For embedding pools (role='embedding'), the operator configures
        an embedding model (e.g., `ollama/nomic-embed-text`). For chat
        pools, this will probably fail — catch the ProviderUnavailable
        and route embeddings through a dedicated embedding pool instead.
        """
        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "input": text,
        }
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"litellm[{self._model}] embed error: {exc}") from exc
        if response.status_code == 429:
            raise RateLimited(f"litellm[{self._model}] embed 429")
        if not response.is_success:
            raise ProviderUnavailable(
                f"litellm[{self._model}] embed {response.status_code}: <response body sanitized>"
            )
        data = response.json()
        # OpenAI-compat shape: {"data": [{"embedding": [...], ...}], "usage": ...}
        items = data.get("data") or []
        if not items or "embedding" not in items[0]:
            raise ProviderUnavailable(f"litellm[{self._model}] embed returned no embedding")
        embedding = items[0]["embedding"]
        usage = data.get("usage") or {}
        tokens_used = int(usage.get("total_tokens", 0)) or (len(text) // 4)
        self._tokens_used += tokens_used
        return list(embedding)

    def generate_image(self, prompt: str) -> str:
        """Call LiteLLM /v1/images/generations. Returns base64-encoded image data."""
        url = f"{self._base_url}/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            response = self._client.post(url, headers=headers, json=body, timeout=60.0)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"litellm[{self._model}] image gen error: {exc}") from exc
        if response.status_code == 429:
            raise RateLimited(f"litellm[{self._model}] image gen 429")
        if not response.is_success:
            raise ProviderUnavailable(
                f"litellm[{self._model}] image gen {response.status_code}: <response body sanitized>"
            )
        data = response.json()
        items = data.get("data") or []
        if not items:
            raise ProviderUnavailable(f"litellm[{self._model}] image gen returned no data")
        b64 = items[0].get("b64_json") or items[0].get("url", "")
        self._tokens_used += len(prompt) // 4
        return b64

    def quota_window(self) -> FreeTierWindow | None:
        now = datetime.now(UTC)
        if now - self._window_started_at >= self._window_duration:
            self._window_started_at = now
            self._tokens_used = 0
        return FreeTierWindow(
            provider=self.name,
            window_kind=self._pool_config.window_kind,
            window_started_at=self._window_started_at,
            window_duration=self._window_duration,
            tokens_allowed=self._tokens_allowed,
            tokens_used=self._tokens_used,
        )

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
