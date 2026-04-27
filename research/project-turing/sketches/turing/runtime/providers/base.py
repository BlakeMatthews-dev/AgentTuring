"""Provider protocol and typed errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FreeTierWindow:
    """A provider's current free-tier accounting window."""

    provider: str
    window_kind: str  # "rpm" | "daily" | "monthly" | "rolling_hours"
    window_started_at: datetime
    window_duration: timedelta
    tokens_allowed: int
    tokens_used: int

    @property
    def headroom(self) -> int:
        return max(0, self.tokens_allowed - self.tokens_used)

    @property
    def window_ends_at(self) -> datetime:
        return self.window_started_at + self.window_duration


class ProviderError(RuntimeError):
    """Base class for provider errors."""


class RateLimited(ProviderError):
    """429 response or local rate-limit prediction."""


class ProviderUnavailable(ProviderError):
    """5xx response or network failure after retries."""


class Provider(Protocol):
    """What a daydream / contradiction / tuner dispatch calls to do real work."""

    name: str

    def complete(self, prompt: str, *, max_tokens: int | None = None) -> str:
        raise NotImplementedError

    def quota_window(self) -> FreeTierWindow | None:
        """Current free-tier window; None if this provider has no free tier."""
        raise NotImplementedError


@runtime_checkable
class EmbeddingProvider(Protocol):
    """A provider that can also produce embeddings."""

    name: str

    def embed(self, text: str) -> list[float]:
        """Return a vector embedding for `text`."""
        raise NotImplementedError

    def quota_window(self) -> FreeTierWindow | None:
        raise NotImplementedError


@runtime_checkable
class ImageGenProvider(Protocol):
    """A provider that can generate images from text prompts."""

    name: str

    def generate_image(self, prompt: str) -> str:
        """Generate an image from a text prompt. Returns base64-encoded PNG."""
        raise NotImplementedError

    def quota_window(self) -> FreeTierWindow | None:
        raise NotImplementedError
