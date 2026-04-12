"""Tool Catalog — registry with multi-tenant cascade and semver versioning.

ADR-K8S-021: tools registered as catalog entries with scope (builtin > tenant > user).
Resolution cascades from user to tenant to builtin, highest-priority wins.
Customer plugins discovered via 'stronghold.tools' entry-point group.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.metadata import entry_points

from stronghold.types.tool import (
    ToolDefinition,  # noqa: TC001  (dataclass field — runtime import needed)
)

logger = logging.getLogger("stronghold.tools.catalog")

# Scope priority: higher number = higher priority in cascade
_SCOPE_PRIORITY = {"builtin": 0, "tenant": 1, "user": 2}


@dataclass(frozen=True)
class CatalogEntry:
    """A tool registered in the catalog with scope and version metadata."""

    definition: ToolDefinition
    version: str = "1.0.0"
    scope: str = "builtin"  # "builtin" | "tenant" | "user"
    tenant_id: str = ""
    user_id: str = ""


def _is_visible(entry: CatalogEntry, tenant_id: str, user_id: str) -> bool:
    """Check if an entry is visible to the given tenant/user scope."""
    if entry.scope == "builtin":
        return True
    if entry.scope == "tenant" and tenant_id and entry.tenant_id == tenant_id:
        return True
    return bool(entry.scope == "user" and user_id and entry.user_id == user_id)


class ToolCatalog:
    """Multi-tenant tool catalog with cascade resolution."""

    def __init__(self) -> None:
        self._entries: list[CatalogEntry] = []

    def register(self, entry: CatalogEntry) -> None:
        """Register a tool in the catalog."""
        self._entries.append(entry)

    def resolve(
        self,
        tool_name: str,
        tenant_id: str = "",
        user_id: str = "",
    ) -> CatalogEntry | None:
        """Resolve a tool by name with cascade: user > tenant > builtin."""
        candidates: list[CatalogEntry] = []
        for entry in self._entries:
            if entry.definition.name != tool_name:
                continue
            if _is_visible(entry, tenant_id, user_id):
                candidates.append(entry)

        if not candidates:
            return None

        # Sort by scope priority descending — highest wins
        candidates.sort(key=lambda e: _SCOPE_PRIORITY.get(e.scope, 0), reverse=True)
        return candidates[0]

    def list_tools(
        self,
        tenant_id: str = "",
        user_id: str = "",
    ) -> list[CatalogEntry]:
        """Return all tools visible to this tenant/user, deduplicated by name (cascade)."""
        seen: dict[str, CatalogEntry] = {}
        for entry in self._entries:
            if not _is_visible(entry, tenant_id, user_id):
                continue
            name = entry.definition.name

            existing = seen.get(name)
            if existing is None or _SCOPE_PRIORITY.get(entry.scope, 0) > _SCOPE_PRIORITY.get(
                existing.scope, 0
            ):
                seen[name] = entry

        return sorted(seen.values(), key=lambda e: e.definition.name)

    def load_plugins(self) -> None:
        """Discover tools from 'stronghold.tools' entry-point group."""
        eps = entry_points()
        group = (
            eps.get("stronghold.tools", [])
            if isinstance(eps, dict)
            else eps.select(group="stronghold.tools")
        )
        for ep in group:
            try:
                tool_fn = ep.load()
                if hasattr(tool_fn, "_catalog_entry"):
                    self.register(tool_fn._catalog_entry)
                    logger.info("Loaded plugin tool: %s", ep.name)
            except Exception:
                logger.warning("Failed to load plugin tool: %s", ep.name, exc_info=True)
