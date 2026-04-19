"""FakeProvider: canned responses with configurable latency and failure modes.

Used for chunk 1 smoke tests and integration tests in later chunks. Never
makes network calls.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from .base import FreeTierWindow, Provider, ProviderUnavailable, RateLimited


class FakeProvider:
    """Returns canned responses.

    Parameters
    ----------
    name: provider identifier
    responses: iterable of canned strings; cycles when exhausted
    latency_s: simulated completion latency
    fail_every: raise RateLimited every N calls (0 = never)
    unavailable_every: raise ProviderUnavailable every N calls (0 = never)
    quota_allowed / quota_used: initial window state (RPM, 60s window by default)
    """

    def __init__(
        self,
        *,
        name: str = "fake",
        responses: list[str] | None = None,
        latency_s: float = 0.0,
        fail_every: int = 0,
        unavailable_every: int = 0,
        quota_allowed: int = 1_000_000,
        quota_used: int = 0,
        window_kind: str = "rpm",
        window_duration: timedelta = timedelta(seconds=60),
    ) -> None:
        self.name = name
        self._responses: Iterator[str] = itertools.cycle(
            responses or ["fake response"]
        )
        self._latency_s = latency_s
        self._fail_every = fail_every
        self._unavailable_every = unavailable_every
        self._call_count = 0
        self._quota_allowed = quota_allowed
        self._quota_used = quota_used
        self._window_started = datetime.now(UTC)
        self._window_kind = window_kind
        self._window_duration = window_duration

    def complete(self, prompt: str, *, max_tokens: int = 512) -> str:
        self._call_count += 1
        if self._fail_every and self._call_count % self._fail_every == 0:
            raise RateLimited(f"fake rate limit on call {self._call_count}")
        if (
            self._unavailable_every
            and self._call_count % self._unavailable_every == 0
        ):
            raise ProviderUnavailable(
                f"fake unavailable on call {self._call_count}"
            )
        if self._latency_s > 0:
            time.sleep(self._latency_s)
        tokens_used = len(prompt) // 4 + max_tokens // 4
        self._quota_used += tokens_used
        return next(self._responses)

    def embed(self, text: str) -> list[float]:
        """Deterministic pseudo-random 64-dim vector from the input hash.

        Same text → same vector, different text → different vector.
        Cosine similarity between unrelated strings ≈ 0; between
        similar strings — well, it's a fake, it's random. Good enough
        for plumbing tests; don't expect meaningful semantic similarity.
        """
        import hashlib
        import struct

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand to 64 floats in [-1, 1] deterministically from the digest.
        out: list[float] = []
        salt = b"turing-fake-embed"
        seed = digest
        for _ in range(8):
            seed = hashlib.sha256(salt + seed).digest()
            for i in range(0, 32, 4):
                v = struct.unpack(">i", seed[i : i + 4])[0]
                out.append(max(-1.0, min(1.0, v / 2**30)))
        self._quota_used += max(1, len(text) // 4)
        return out[:64]

    def quota_window(self) -> FreeTierWindow | None:
        # Roll the window forward if it has expired.
        now = datetime.now(UTC)
        if now - self._window_started >= self._window_duration:
            self._window_started = now
            self._quota_used = 0
        return FreeTierWindow(
            provider=self.name,
            window_kind=self._window_kind,
            window_started_at=self._window_started,
            window_duration=self._window_duration,
            tokens_allowed=self._quota_allowed,
            tokens_used=self._quota_used,
        )
