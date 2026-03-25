"""Agent store protocol: CRUD for runtime agent management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.agent import AgentIdentity


@runtime_checkable
class AgentStore(Protocol):
    """Manages agent definitions and lifecycle.

    Supports runtime creation, update, and deletion of agents.
    Import/export in GitAgent format (directory-based YAML + markdown).
    """

    async def create(
        self,
        identity: AgentIdentity,
        soul_content: str,
        rules_content: str = "",
    ) -> str:
        """Create a new agent. Returns agent name.

        Raises ValueError if name already exists.
        """
        ...

    async def get(self, name: str) -> dict[str, Any] | None:
        """Get agent details by name. Returns None if not found."""
        ...

    async def list_all(self) -> list[dict[str, Any]]:
        """List all registered agents."""
        ...

    async def update(
        self,
        name: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update agent config. Returns updated details.

        Raises ValueError if not found.
        """
        ...

    async def delete(self, name: str) -> bool:
        """Delete an agent. Returns True if deleted, False if not found."""
        ...

    async def export_gitagent(self, name: str) -> bytes:
        """Export agent as GitAgent zip file. Raises ValueError if not found."""
        ...

    async def import_gitagent(self, zip_data: bytes) -> str:
        """Import agent from GitAgent zip. Returns agent name."""
        ...
