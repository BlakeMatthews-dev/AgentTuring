"""In-memory rate limiter: sliding window counter per key.

Uses a deque of timestamps per key. Each check prunes expired entries,
then counts remaining. O(1) amortized per check.

Enforces both RPM (requests per minute) and burst limits.
Periodically evicts stale keys to prevent unbounded memory growth.

For distributed deployments, replace with Redis-backed implementation
using the same RateLimiter protocol.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.config import RateLimitConfig

# Evict keys not seen in this many seconds
_KEY_EVICTION_AGE_S = 300  # 5 minutes
# Run eviction every N check() calls
_EVICTION_INTERVAL = 1000


class InMemoryRateLimiter:
    """Sliding window rate limiter. Implements RateLimiter protocol."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        if config is None:
            from stronghold.types.config import (  # noqa: PLC0415
                RateLimitConfig as DefaultConfig,
            )

            config = DefaultConfig()
        cfg = config
        self._rpm = cfg.requests_per_minute
        self._burst = cfg.burst_limit
        self._enabled = cfg.enabled
        self._window = 60.0  # 1 minute sliding window
        self._burst_window = 1.0  # 1 second burst window
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._check_count = 0
        self._last_eviction = time.monotonic()

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check if request is allowed. Returns (allowed, rate_limit_headers)."""
        if not self._enabled:
            return True, {}

        now = time.monotonic()
        window = self._windows[key]

        # Prune expired entries
        cutoff = now - self._window
        while window and window[0] < cutoff:
            window.popleft()

        remaining = max(self._rpm - len(window), 0)
        reset_seconds = int(self._window - (now - window[0])) if window else int(self._window)

        headers = {
            "X-RateLimit-Limit": str(self._rpm),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_seconds),
        }

        # Check RPM limit
        if len(window) >= self._rpm:
            return False, headers

        # Check burst limit: count requests in the last 1 second
        if self._burst > 0:
            burst_cutoff = now - self._burst_window
            recent = sum(1 for ts in window if ts >= burst_cutoff)
            if recent >= self._burst:
                headers["X-RateLimit-Remaining"] = "0"
                return False, headers

        # Periodic eviction of stale keys
        self._check_count += 1
        if self._check_count >= _EVICTION_INTERVAL:
            self._evict_stale_keys(now)

        return True, headers

    async def record(self, key: str) -> None:
        """Record a request against the key."""
        if not self._enabled:
            return
        self._windows[key].append(time.monotonic())

    def _evict_stale_keys(self, now: float) -> None:
        """Remove keys whose most recent entry is older than eviction age."""
        self._check_count = 0
        self._last_eviction = now
        eviction_cutoff = now - _KEY_EVICTION_AGE_S
        stale_keys = [k for k, v in self._windows.items() if not v or v[-1] < eviction_cutoff]
        for k in stale_keys:
            del self._windows[k]
