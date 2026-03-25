"""Skill protocols: loader, forge, marketplace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.memory import Learning
    from stronghold.types.skill import SkillDefinition, SkillMetadata
    from stronghold.types.tool import ToolDefinition


@runtime_checkable
class SkillLoader(Protocol):
    """Loads and manages skill definitions."""

    def load_all(self) -> list[SkillDefinition]:
        """Load all skills from filesystem."""
        ...

    def merge_into_tools(
        self,
        existing_tools: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Merge skill-defined tools into the tool list."""
        ...


@runtime_checkable
class SkillForge(Protocol):
    """AI-generated skill creation and mutation."""

    async def forge(self, request: str) -> SkillDefinition:
        """Generate a new skill from a natural language request."""
        ...

    async def mutate(
        self,
        skill_name: str,
        learning: Learning,
    ) -> dict[str, Any]:
        """Mutate an existing skill by baking a promoted learning into its system prompt.

        Returns: {"status": "mutated"|"skipped"|"error", "old_hash": ..., "new_hash": ...}
        """
        ...


@runtime_checkable
class SkillMarketplace(Protocol):
    """Community skill discovery and installation."""

    async def search(self, query: str, max_results: int = 10) -> list[SkillMetadata]:
        """Search for skills."""
        ...

    async def install(self, url: str, trust_tier: str = "t2") -> SkillDefinition:
        """Install a skill from a URL."""
        ...

    def uninstall(self, name: str) -> None:
        """Uninstall a skill by name."""
        ...
