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
        """Non-streaming completion with automatic model fallback on 429/5xx."""
        models_to_try = [model]
        if fallback_models:
            models_to_try.extend(fallback_models)
        elif hasattr(self, "_fallback_models") and self._fallback_models:
            models_to_try.extend(self._fallback_models)  # set dynamically by container

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

        last_error: Exception | None = None

        for i, try_model in enumerate(models_to_try):
            body["model"] = try_model

            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/v1/chat/completions",
                        json=body,
                        headers=headers,
                    )

                if resp.status_code == 200:  # noqa: PLR2004
                    return resp.json()  # type: ignore[no-any-return]

                if resp.status_code in (429, 500, 502, 503):
                    logger.warning(
                        "Model %s returned %d, trying next (%d/%d)",
                        try_model,
                        resp.status_code,
                        i + 1,
                        len(models_to_try),
                    )
                    # Brief pause before trying next model
                    await asyncio.sleep(1)
                    last_error = httpx.HTTPStatusError(
                        f"{resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    continue

                # Other errors (400, 401, etc.) — don't retry
                resp.raise_for_status()

            except httpx.ConnectError as e:
                logger.warning("Connection error for %s: %s", try_model, e)
                last_error = e
                continue

        # All models failed
        if last_error:
            raise last_error
        msg = "No models available"
        raise RuntimeError(msg)

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
