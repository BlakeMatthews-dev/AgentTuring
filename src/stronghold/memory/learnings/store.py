"""Learning store: in-memory implementation.

PostgreSQL version uses asyncpg. This is for testing and local dev.
All queries are org-scoped — learnings from org-A are invisible to org-B.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.memory import Learning

logger = logging.getLogger("stronghold.learnings")


MAX_LEARNINGS = 10000  # Per-store cap to prevent OOM


class InMemoryLearningStore:
    """In-memory learning store for testing.

    All query methods filter by org_id when provided,
    ensuring multi-tenant isolation at the data layer.
    Capped at MAX_LEARNINGS to prevent OOM via learning flooding.
    """

    def __init__(self, max_learnings: int = MAX_LEARNINGS) -> None:
        self._learnings: list[Learning] = []
        self._next_id = 1
        self._max_learnings = max_learnings

    async def store(self, learning: Learning) -> int:
        """Store a learning, dedup against existing within same org."""
        new_keys = set(learning.trigger_keys)
        for existing in self._learnings:
            if existing.tool_name != learning.tool_name:
                continue
            if existing.agent_id != learning.agent_id:
                continue
            if existing.org_id != learning.org_id:
                continue  # Never dedup across orgs
            if existing.status != "active":
                continue
            existing_keys = set(existing.trigger_keys)
            overlap = len(existing_keys & new_keys) / max(len(existing_keys | new_keys), 1)
            if overlap >= 0.5:
                logger.info(
                    "Learning dedup overwrite: id=%s, old_keys=%s, new_keys=%s, overlap=%.2f",
                    existing.id,
                    existing.trigger_keys,
                    learning.trigger_keys,
                    overlap,
                )
                existing.learning = learning.learning
                existing.trigger_keys = learning.trigger_keys
                return existing.id or 0

        # Evict oldest if at capacity
        if len(self._learnings) >= self._max_learnings:
            self._learnings.pop(0)

        learning.id = self._next_id
        self._next_id += 1
        self._learnings.append(learning)
        return learning.id

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find learnings relevant to user text, scoped by org."""
        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []

        for learning in self._learnings:
            if learning.status != "active":
                continue
            if agent_id and learning.agent_id != agent_id:
                continue
            # Org isolation: STRICT — skip learnings that don't match caller's org.
            # If learning has org_id set, it MUST match. If caller has org_id,
            # learnings without org_id are excluded (no unscoped data leakage).
            if org_id and learning.org_id != org_id:
                continue
            if not org_id and learning.org_id:
                continue  # Caller has no org = system; skip org-scoped learnings

            score = sum(1 for k in learning.trigger_keys if k and k in text_lower)
            if score > 0:
                scored.append((score, learning))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for used learnings."""
        id_set = set(learning_ids)
        for learning in self._learnings:
            if learning.id in id_set:
                learning.hit_count += 1

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings that hit threshold, scoped by org."""
        promoted: list[Learning] = []
        for learning in self._learnings:
            if learning.status != "active" or learning.hit_count < threshold:
                continue
            # Org isolation: only promote within caller's org
            if org_id and learning.org_id != org_id:
                continue
            if not org_id and learning.org_id:
                continue  # System caller: skip org-scoped learnings
            learning.status = "promoted"
            promoted.append(learning)
        return promoted

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
    ) -> list[Learning]:
        """Get promoted learnings, scoped by org."""
        results: list[Learning] = []
        for lr in self._learnings:
            if lr.status != "promoted":
                continue
            # Strict org isolation (same logic as find_relevant)
            if org_id and lr.org_id != org_id:
                continue
            if not org_id and lr.org_id:
                continue
            results.append(lr)
        return results

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings for an org (admin endpoint)."""
        results: list[Learning] = []
        for lr in self._learnings:
            if org_id and org_id != "__system__" and lr.org_id != org_id:
                continue
            results.append(lr)
            if len(results) >= limit:
                break
        return results
