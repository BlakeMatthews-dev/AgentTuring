"""LiteLLM client: implements LLMClient protocol via httpx.

On 429 or 5xx: tries fallback models from the candidate list.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger("stronghold.llm")


class LiteLLMClient:
    """Forwards requests to LiteLLM proxy with model fallback on errors."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
        fallback_models: list[str] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming completion with exhaustive model fallback.

        On 429/5xx/400 (cooldown): cycles through explicit fallbacks,
        then fetches ALL available models from LiteLLM and tries each.
        """
        models_to_try = [model]
        if fallback_models:
            models_to_try.extend(fallback_models)
        elif hasattr(self, "_fallback_models") and self._fallback_models:
            models_to_try.extend(self._fallback_models)

        body: dict[str, Any] = {"messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if metadata:
            body["metadata"] = metadata

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        tried: set[str] = set()
        last_error: Exception | None = None

        # Phase 1: try explicit models
        for try_model in models_to_try:
            result = await self._try_model(try_model, body, headers)
            tried.add(try_model)
            if isinstance(result, dict):
                return result
            last_error = result

        # Phase 2: fetch all available models and try each
        available = await self._fetch_available_models(headers)
        for try_model in available:
            if try_model in tried:
                continue
            result = await self._try_model(try_model, body, headers)
            tried.add(try_model)
            if isinstance(result, dict):
                logger.info("Fallback succeeded on model %s (tried %d)", try_model, len(tried))
                return result
            last_error = result

        # All models exhausted
        logger.warning("All %d models exhausted", len(tried))
        if last_error:
            raise last_error
        msg = f"No models available (tried {len(tried)})"
        raise RuntimeError(msg)

    async def _try_model(
        self,
        model: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any] | Exception:
        """Try a single model. Returns response dict on success, Exception on failure."""
        body["model"] = model
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=body,
                    headers=headers,
                )

            if resp.status_code == 200:  # noqa: PLR2004
                return resp.json()  # type: ignore[no-any-return]

            # Retryable: 402 (quota), 408 (timeout), 429, 400 (cooldown), 422, 5xx
            if resp.status_code in (400, 402, 408, 422, 429, 500, 502, 503):
                logger.debug("Model %s returned %d, skipping", model, resp.status_code)
                await asyncio.sleep(0.2)
                return httpx.HTTPStatusError(
                    f"{resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            # Non-retryable (401, 403, etc.)
            resp.raise_for_status()

        except httpx.ConnectError as e:
            logger.debug("Connection error for %s: %s", model, e)
            return e

        return RuntimeError(f"Unexpected state for model {model}")

    async def _fetch_available_models(
        self,
        headers: dict[str, str],
    ) -> list[str]:
        """Fetch all model IDs from LiteLLM /v1/models endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/v1/models",
                    headers=headers,
                )
            if resp.status_code == 200:  # noqa: PLR2004
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                logger.info("Fetched %d available models for fallback", len(models))
                return models
        except Exception:
            logger.warning("Failed to fetch model list for fallback")
        return []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming completion. Yields SSE chunks."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with (
            httpx.AsyncClient(timeout=180.0) as client,
            client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=body,
                headers=headers,
            ) as resp,
        ):
            async for chunk in resp.aiter_text():
                yield chunk
