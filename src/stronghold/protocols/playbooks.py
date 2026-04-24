"""Playbook protocols: executor and execution context.

A playbook composes multiple backend calls server-side and returns a Brief
(markdown shaped for reasoning). It is a peer of the thin-tool surface in
src/stronghold/tools/; both are registered into their own registries and
surfaced to the agent loop through the same ToolExecutor transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.playbooks.base import PlaybookDefinition
    from stronghold.playbooks.brief import Brief
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.types.auth import AuthContext


@dataclass
class PlaybookContext:
    """Injected dependencies for playbook execution.

    Kept as a mutable dataclass (not frozen) so phases can add fields
    (vault, feature flags) without re-threading every call site.
    """

    auth: AuthContext
    llm: LLMClient | None = None
    warden: Any | None = None
    tracer: TracingBackend | None = None


@runtime_checkable
class PlaybookExecutor(Protocol):
    """Executes a single playbook and returns a Brief."""

    @property
    def definition(self) -> PlaybookDefinition:
        """Static metadata describing this playbook."""
        ...

    async def execute(
        self,
        inputs: dict[str, Any],
        ctx: PlaybookContext,
    ) -> Brief:
        """Run the playbook with user-supplied inputs and return a Brief."""
        ...


@runtime_checkable
class PlaybookRegistry(Protocol):
    """Manages playbook definitions and executor lookup."""

    def register(self, executor: PlaybookExecutor) -> None:
        """Register a playbook executor by its definition.name."""
        ...

    def get(self, name: str) -> PlaybookExecutor | None:
        """Resolve an executor by name."""
        ...

    def list_all(self) -> list[PlaybookDefinition]:
        """Enumerate every registered playbook's definition."""
        ...
