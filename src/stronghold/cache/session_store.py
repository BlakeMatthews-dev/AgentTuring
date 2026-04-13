"""Redis-backed session store.

Stores conversation history as JSON lists in Redis with TTL-based expiry.
Implements the same interface as InMemorySessionStore and PgSessionStore.

Each message is stored as JSON with a `_ts` field for per-message TTL filtering.
Session keys are org-scoped — the store validates ownership as defense-in-depth.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis  # noqa: TC002

logger = logging.getLogger("stronghold.cache.session_store")


class RedisSessionStore:
    """Distributed session store backed by Redis.

    Each session is a Redis list of JSON-encoded messages with timestamps.
    Sessions auto-expire after ttl_seconds of inactivity.
    Per-message TTL filtering on read matches InMemorySessionStore behavior.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        ttl_seconds: int = 3600,
        max_messages: int = 100,
        key_prefix: str = "stronghold:session:",
    ) -> None:
        self._redis = redis
        self._ttl = ttl_seconds
        self._max = max_messages
        self._prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Get recent messages for a session, filtered by per-message TTL.

        Session IDs must be org-scoped (format: org/team/user:name).
        Bare session IDs are rejected with ValueError.
        """
        if "/" not in session_id:
            err = (
                f"session_id must be org-scoped (format: org/user:name), "
                f"got bare id: {session_id[:20]!r}"
            )
            raise ValueError(err)
        limit = max_messages or self._max
        ttl = ttl_seconds or self._ttl
        cutoff = time.time() - ttl

        rkey = self._key(session_id)
        raw: list[Any] = await self._redis.lrange(rkey, 0, -1)  # type: ignore[misc]
        if not raw:
            return []

        # Refresh key-level TTL on access
        await self._redis.expire(rkey, self._ttl)

        # Filter by per-message timestamp, return only role+content.
        # Skip (log) any poisoned/non-JSON entries rather than crashing the
        # whole session retrieval.
        result: list[dict[str, str]] = []
        for item in raw:
            try:
                msg = json.loads(item)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning(
                    "Skipping poisoned session entry in %s",
                    session_id,
                )
                continue
            if not isinstance(msg, dict):
                continue
            ts = msg.pop("_ts", 0)
            if ts >= cutoff:
                result.append({"role": msg.get("role", ""), "content": msg.get("content", "")})

        # Return most recent N
        return result[-limit:]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to a session with timestamps."""
        if "/" not in session_id:
            err = (
                f"session_id must be org-scoped (format: org/user:name), "
                f"got bare id: {session_id[:20]!r}"
            )
            raise ValueError(err)
        if not messages:
            return

        now = time.time()
        rkey = self._key(session_id)
        pipe = self._redis.pipeline()
        for msg in messages:
            # SEC-009: skip non-dict entries to avoid AttributeError on .get()
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            # Store with timestamp for per-message TTL filtering
            entry = {"role": role, "content": content, "_ts": now}
            pipe.rpush(rkey, json.dumps(entry))
        # Trim to max length
        pipe.ltrim(rkey, -self._max, -1)
        # Set/refresh key-level TTL
        pipe.expire(rkey, self._ttl)
        await pipe.execute()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        if "/" not in session_id:
            err = (
                f"session_id must be org-scoped (format: org/user:name), "
                f"got bare id: {session_id[:20]!r}"
            )
            raise ValueError(err)
        await self._redis.delete(self._key(session_id))
