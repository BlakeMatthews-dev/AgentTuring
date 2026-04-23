"""InMemoryCheckpointStore: in-memory SessionCheckpoint store (S1.3).

Production deployments should use `PostgresCheckpointStore` (not yet implemented
in this spec — the schema is just four indexable columns: checkpoint_id,
org_id, user_id, team_id, created_at). This in-memory implementation is for
testing and single-process deployments.

All operations are org-scoped. `load(id, org_id=X)` for a checkpoint saved
under org Y returns None, never raises — preventing existence-leak via error.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.memory import SessionCheckpoint


class InMemoryCheckpointStore:
    """Thread-safe in-memory SessionCheckpoint store."""

    def __init__(self) -> None:
        self._by_id: dict[str, SessionCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: SessionCheckpoint) -> str:
        """Persist a checkpoint and return its id. Generates a UUID if unset."""
        cp_id = checkpoint.checkpoint_id or uuid.uuid4().hex
        stored = replace(checkpoint, checkpoint_id=cp_id)
        async with self._lock:
            self._by_id[cp_id] = stored
        return cp_id

    async def load(
        self,
        checkpoint_id: str,
        *,
        org_id: str,
    ) -> SessionCheckpoint | None:
        """Load a checkpoint. Cross-org access returns None (silent tenant isolation)."""
        async with self._lock:
            cp = self._by_id.get(checkpoint_id)
        if cp is None:
            return None
        if cp.org_id != org_id:
            return None
        return cp

    async def list_recent(
        self,
        *,
        org_id: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        team_id: str | None = None,
        limit: int = 20,
    ) -> list[SessionCheckpoint]:
        """List checkpoints matching the scope filter, ordered by created_at desc."""
        async with self._lock:
            candidates = [cp for cp in self._by_id.values() if cp.org_id == org_id]

        if user_id is not None:
            candidates = [cp for cp in candidates if cp.user_id == user_id]
        if agent_id is not None:
            candidates = [cp for cp in candidates if cp.agent_id == agent_id]
        if team_id is not None:
            candidates = [cp for cp in candidates if cp.team_id == team_id]

        candidates.sort(key=lambda cp: cp.created_at, reverse=True)
        return candidates[:limit]
