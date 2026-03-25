"""PostgreSQL-backed prompt library.

In-memory implementation for testing. PostgreSQL version uses asyncpg.
"""

from __future__ import annotations

from typing import Any


class InMemoryPromptManager:
    """In-memory prompt manager for testing and local dev.

    C4/C5 fix: All prompt keys are org-scoped. Internal prompts (agent souls,
    system prompts) use the raw name (no org prefix) because they're shared
    infrastructure. Org-specific prompts use "org_id:name" as the key.
    """

    def __init__(self) -> None:
        # {name: {version: (content, config)}}
        self._versions: dict[str, dict[int, tuple[str, dict[str, Any]]]] = {}
        # {name: {label: version}}
        self._labels: dict[str, dict[str, int]] = {}
        self._next_version: dict[str, int] = {}

    @staticmethod
    def _scoped_name(name: str, org_id: str = "") -> str:
        """Build org-scoped prompt key. System/agent prompts use raw name."""
        # Agent soul prompts and system prompts are shared infrastructure
        is_shared = name.startswith("agent.") or name.startswith("system.")
        if not org_id or org_id == "__system__" or is_shared:
            return name
        return f"{org_id}:{name}"

    async def get(self, name: str, *, label: str = "production", org_id: str = "") -> str:
        """Fetch prompt content by name and label (org-scoped)."""
        content, _ = await self.get_with_config(name, label=label, org_id=org_id)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
        org_id: str = "",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata (org-scoped)."""
        key = self._scoped_name(name, org_id)
        labels = self._labels.get(key, {})
        version = labels.get(label)
        if version is None:
            # Try latest version
            versions = self._versions.get(key, {})
            if not versions:
                return ("", {})
            version = max(versions)

        versions = self._versions.get(key, {})
        entry = versions.get(version)
        if entry is None:
            return ("", {})
        return entry

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
        org_id: str = "",
    ) -> None:
        """Create a new version of a prompt (org-scoped)."""
        key = self._scoped_name(name, org_id)
        if key not in self._versions:
            self._versions[key] = {}
            self._labels[key] = {}
            self._next_version[key] = 1

        version = self._next_version[key]
        self._next_version[key] = version + 1
        self._versions[key][version] = (content, config or {})

        if label:
            self._labels[key][label] = version
        # Always update "latest"
        self._labels[key]["latest"] = version
        # First version gets "production" by default
        if version == 1 and "production" not in self._labels[key]:
            self._labels[key]["production"] = version
