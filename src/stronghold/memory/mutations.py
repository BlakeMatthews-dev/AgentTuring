"""Skill mutation store: in-memory implementation.

Tracks when skills are rewritten from promoted learnings.
Same API as Conductor's record_skill_mutation() / list_skill_mutations().
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.memory import SkillMutation


class InMemorySkillMutationStore:
    """In-memory skill mutation store for testing."""

    def __init__(self) -> None:
        self._mutations: list[SkillMutation] = []
        self._next_id = 1

    async def record(self, mutation: SkillMutation) -> int:
        """Record a skill mutation. Returns mutation ID."""
        mutation.id = self._next_id
        self._next_id += 1
        self._mutations.append(mutation)
        return mutation.id

    async def list_mutations(self, limit: int = 50) -> list[SkillMutation]:
        """List recent mutations."""
        return self._mutations[-limit:]
