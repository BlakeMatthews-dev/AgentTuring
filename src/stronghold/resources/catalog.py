"""Resource Catalog — URI-addressable read-only state with vault injection.

ADR-K8S-023: resources are URI-addressable read-only data resolved on demand.
URI scheme: stronghold://global/..., stronghold://tenant/<id>/..., stronghold://user/<id>/...
Per-call vault credential injection at the resolver layer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

logger = logging.getLogger("stronghold.resources.catalog")

# URI pattern: stronghold://<scope>/<path>
_URI_RE = re.compile(r"^stronghold://(?P<scope>global|tenant|user)/(?P<path>.+)$")


@dataclass(frozen=True)
class ResourceEntry:
    """A registered resource template."""

    uri_template: str  # e.g. "stronghold://user/{user_id}/github/repos"
    description: str = ""
    scope: str = "global"  # "global" | "tenant" | "user"
    mime_type: str = "application/json"


@dataclass(frozen=True)
class ResolvedResource:
    """The result of resolving a resource URI."""

    uri: str
    content: str
    mime_type: str = "application/json"


# Resolver signature: (path, credentials) -> content string
ResolverFn = Callable[[str, dict[str, str]], Awaitable[str]]


class ResourceCatalog:
    """Multi-scope resource catalog with URI resolution and vault injection."""

    def __init__(self) -> None:
        self._entries: list[ResourceEntry] = []
        self._resolvers: dict[str, ResolverFn] = {}  # pattern prefix -> resolver

    def register(self, entry: ResourceEntry, resolver: ResolverFn) -> None:
        """Register a resource with its resolver function."""
        self._entries.append(entry)
        # Extract the static prefix for matching (before any {param})
        prefix = entry.uri_template.split("{")[0].rstrip("/")
        self._resolvers[prefix] = resolver

    def list_resources(
        self, tenant_id: str = "", user_id: str = "",
    ) -> list[ResourceEntry]:
        """Return all resources visible to this tenant/user."""
        results: list[ResourceEntry] = []
        for entry in self._entries:
            if entry.scope == "global":
                results.append(entry)
            elif entry.scope == "tenant" and tenant_id:
                results.append(entry)
            elif entry.scope == "user" and user_id:
                results.append(entry)
        return sorted(results, key=lambda e: e.uri_template)

    async def resolve(
        self,
        uri: str,
        tenant_id: str = "",
        user_id: str = "",
        credentials: dict[str, str] | None = None,
    ) -> ResolvedResource | None:
        """Resolve a resource URI to its content.

        Credentials are injected from the vault at call time — the resolver
        receives them as a dict (e.g. {"github_token": "ghp_..."}).
        """
        match = _URI_RE.match(uri)
        if not match:
            logger.warning("Invalid resource URI: %s", uri)
            return None

        scope = match.group("scope")
        path = match.group("path")

        # Normalize path to prevent traversal attacks (../)
        import posixpath
        path = posixpath.normpath(path)
        if path.startswith("..") or "/../" in f"/{path}/":
            logger.warning("Path traversal attempt blocked: %s", uri)
            return None

        # Enforce tenant/user namespace isolation
        if scope == "user":
            # URI must start with the user's ID
            if not user_id or not path.startswith(f"{user_id}/"):
                logger.warning(
                    "Resource access denied: user=%s tried to access user path=%s",
                    user_id, path,
                )
                return None
        elif scope == "tenant":
            if not tenant_id or not path.startswith(f"{tenant_id}/"):
                logger.warning(
                    "Resource access denied: tenant=%s tried to access tenant path=%s",
                    tenant_id, path,
                )
                return None

        # Find matching resolver by prefix
        full_path = f"stronghold://{scope}/{path}"
        resolver = self._find_resolver(full_path)
        if not resolver:
            logger.warning("No resolver for URI: %s", uri)
            return None

        try:
            content = await resolver(path, credentials or {})
            entry = self._find_entry(full_path)
            mime_type = entry.mime_type if entry else "application/json"
            return ResolvedResource(uri=uri, content=content, mime_type=mime_type)
        except Exception:
            logger.warning("Resolver failed for URI: %s", uri, exc_info=True)
            return None

    def _find_resolver(self, uri: str) -> ResolverFn | None:
        for prefix, resolver in self._resolvers.items():
            if uri.startswith(prefix):
                return resolver
        return None

    def _find_entry(self, uri: str) -> ResourceEntry | None:
        for entry in self._entries:
            prefix = entry.uri_template.split("{")[0].rstrip("/")
            if uri.startswith(prefix):
                return entry
        return None
