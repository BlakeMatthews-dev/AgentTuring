"""LLM client protocol — abstraction over LiteLLM/Ollama/direct API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@runtime_checkable
class LLMClient(Protocol):
    """Abstraction over any OpenAI-compatible LLM backend."""

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
    ) -> dict[str, Any]:
        """Non-streaming completion. Returns OpenAI-format response dict."""
        ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming completion. Yields SSE chunks.

        Implementations should be async generators (async def + yield).
        The return type is AsyncIterator, not a coroutine wrapping one.
        """
        ...
