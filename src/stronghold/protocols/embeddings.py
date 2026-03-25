"""Embedding client protocol — abstraction over any embedding provider.

Pluggable: Ollama, OpenAI, Cohere, sentence-transformers, or any provider
that can convert text to vectors. NoopEmbeddingClient for testing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
    """Converts text to embedding vectors."""

    @property
    def dimension(self) -> int:
        """The dimensionality of returned vectors."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns a vector of `dimension` floats."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of vectors."""
        ...
