"""Session store: conversation history for thin clients.

In-memory implementation for testing. PostgreSQL version uses asyncpg.
Session IDs are org-scoped: format is "org_id/team_id/user_id:session_name".
The store itself doesn't enforce org isolation — callers must use scoped IDs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from stronghold.types.session import SessionConfig

logger = logging.getLogger("stronghold.sessions.store")


def build_session_id(
    org_id: str,
    team_id: str,
    user_id: str,
    session_name: str,
) -> str:
    """Build an org-scoped session ID.

    Format: "org_id/team_id/user_id:session_name"
    This ensures sessions are namespaced by org+team+user.
    """
    return f"{org_id}/{team_id}/{user_id}:{session_name}"


def validate_session_ownership(
    session_id: str,
    org_id: str,
) -> bool:
    """Validate that a session_id belongs to the given org.

    Returns False if the session_id doesn't start with the org prefix.
    """
    if not org_id:
        return False  # Empty org_id must not bypass validation
    return session_id.startswith(f"{org_id}/")


def validate_and_build_session_id(
    raw_session_id: str | None,
    org_id: str,
    team_id: str = "",
    user_id: str = "",
) -> str | None:
    """Validate or auto-scope a session ID.

    - None → None (no session)
    - Already scoped (contains /) → validate ownership
    - Bare name → auto-scope to org/team/user:name

    Raises ValueError on invalid format or ownership mismatch.
    """
    if raw_session_id is None:
        return None

    import re  # noqa: PLC0415

    if not re.match(r"^[\w/:\-]+$", raw_session_id):
        msg = "Invalid session ID format"
        raise ValueError(msg)

    # Already org-scoped
    if "/" in raw_session_id:
        if not validate_session_ownership(raw_session_id, org_id):
            msg = "Session does not belong to caller's organization"
            raise ValueError(msg)
        return raw_session_id

    # Bare name → auto-scope
    return build_session_id(org_id, team_id or "_", user_id or "_", raw_session_id)


class InMemorySessionStore:
    """In-memory session store for testing and local dev."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self._config = config or SessionConfig()
        # {session_id: [(seq, role, content, timestamp)]}
        self._sessions: dict[str, list[tuple[int, str, str, float]]] = defaultdict(list)
        self._next_seq: dict[str, int] = defaultdict(int)

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        max_msgs = max_messages or self._config.max_messages
        ttl = ttl_seconds or self._config.ttl_seconds
        cutoff = time.time() - ttl

        entries = self._sessions.get(session_id, [])
        # Filter by TTL
        valid = [(seq, role, content, ts) for seq, role, content, ts in entries if ts >= cutoff]
        # Take most recent
        valid.sort(key=lambda x: x[0])
        valid = valid[-max_msgs:]

        return [{"role": role, "content": content} for _, role, content, _ in valid]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to session history."""
        now = time.time()
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            seq = self._next_seq[session_id]
            self._next_seq[session_id] = seq + 1
            self._sessions[session_id].append((seq, role, content, now))

        # Prune on write
        ttl = self._config.ttl_seconds
        cutoff = now - ttl
        entries = self._sessions[session_id]
        self._sessions[session_id] = [e for e in entries if e[3] >= cutoff]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)
        self._next_seq.pop(session_id, None)
