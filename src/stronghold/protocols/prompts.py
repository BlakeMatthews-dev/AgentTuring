"""Prompt manager protocol — PostgreSQL-backed prompt library."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PromptManager(Protocol):
    """Fetches and manages versioned prompts."""

    async def get(self, name: str, *, label: str = "production") -> str:
        """Fetch a prompt by name and label."""
        ...

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata."""
        ...

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a new version of a prompt."""
        ...
