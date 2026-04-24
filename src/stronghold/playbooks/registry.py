"""InMemoryPlaybookRegistry: discovery for agent-oriented playbooks.

Parallels InMemoryToolRegistry in src/stronghold/tools/registry.py:20. Kept
separate from the thin-tool registry so the two surfaces coexist during
the github(action=…) → playbook migration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.playbooks.base import PlaybookDefinition
    from stronghold.protocols.playbooks import PlaybookExecutor

logger = logging.getLogger("stronghold.playbooks.registry")


class DuplicatePlaybookError(Exception):
    """Raised when registering a playbook whose name is already taken."""


class InMemoryPlaybookRegistry:
    """In-memory registry mapping playbook name → executor."""

    def __init__(self) -> None:
        self._executors: dict[str, PlaybookExecutor] = {}

    def register(self, executor: PlaybookExecutor) -> None:
        name = executor.definition.name
        if name in self._executors:
            raise DuplicatePlaybookError(f"Playbook '{name}' already registered")
        self._executors[name] = executor
        logger.debug("Registered playbook: %s", name)

    def get(self, name: str) -> PlaybookExecutor | None:
        return self._executors.get(name)

    def list_all(self) -> list[PlaybookDefinition]:
        return [e.definition for e in self._executors.values()]

    def names(self) -> list[str]:
        return list(self._executors.keys())

    def __len__(self) -> int:
        return len(self._executors)

    def __contains__(self, name: str) -> bool:
        return name in self._executors
