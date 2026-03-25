"""External MCP registry connectors.

Stronghold aggregates servers from multiple MCP registries,
scans them for security issues, and offers one-click deploy.

Supported registries:
- Smithery (6,000+ servers, semantic search)
- Official MCP Registry (modelcontextprotocol.io, OpenAPI)
- Glama (hosted gateway model)
- mcp.so (community directory)
- Stronghold built-in catalog (pre-vetted, official images)

Flow: Search → Scan → Review → Containerize → Deploy → Govern
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("stronghold.mcp.registries")

_SEARCH_TIMEOUT = 8.0


@dataclass
class RegistryServer:
    """An MCP server discovered from an external registry."""

    name: str
    description: str = ""
    author: str = ""
    registry: str = ""  # smithery, official, glama, mcp.so
    repo_url: str = ""
    homepage: str = ""
    verified: bool = False
    use_count: int = 0
    image: str = ""  # Docker image if known
    tags: tuple[str, ...] = ()
    # Security scan results (populated after scan)
    scan_status: str = "unscanned"  # unscanned, clean, flagged, blocked
    scan_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "registry": self.registry,
            "repo_url": self.repo_url,
            "homepage": self.homepage,
            "verified": self.verified,
            "use_count": self.use_count,
            "image": self.image,
            "tags": list(self.tags),
            "scan_status": self.scan_status,
            "scan_flags": self.scan_flags,
        }


# ── Registry Connectors ──────────────────────────────────────


async def search_smithery(
    query: str,
    *,
    api_key: str = "",
    page: int = 1,
    page_size: int = 10,
) -> list[RegistryServer]:
    """Search Smithery registry (6,000+ MCP servers).

    API: https://registry.smithery.ai/servers?q=<query>
    Auth: Bearer token (optional for search, required for details)
    """
    results: list[RegistryServer] = []
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://registry.smithery.ai/servers",
                params={"q": query, "page": page, "pageSize": page_size},
                headers=headers,
            )
            if resp.status_code == 200:  # noqa: PLR2004
                data = resp.json()
                for s in data.get("servers", []):
                    results.append(
                        RegistryServer(
                            name=s.get("qualifiedName", s.get("displayName", "")),
                            description=s.get("description", ""),
                            author=s.get("qualifiedName", "").split("/")[0]
                            if "/" in s.get("qualifiedName", "")
                            else "",
                            registry="smithery",
                            homepage=s.get("homepage", ""),
                            verified=s.get("verified", False),
                            use_count=s.get("useCount", 0),
                        )
                    )
            else:
                logger.warning("Smithery API returned %d", resp.status_code)
    except Exception as e:
        logger.warning("Smithery search failed: %s", e)

    return results


async def search_official_registry(
    query: str,
    *,
    page_size: int = 10,
) -> list[RegistryServer]:
    """Search the official MCP Registry (modelcontextprotocol.io).

    API: https://registry.modelcontextprotocol.io/api/servers?q=<query>
    No auth required.
    """
    results: list[RegistryServer] = []
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://registry.modelcontextprotocol.io/api/servers",
                params={"q": query, "count": page_size},
            )
            if resp.status_code == 200:  # noqa: PLR2004
                data = resp.json()
                servers = data.get("servers", data) if isinstance(data, dict) else data
                for s in servers[:page_size]:
                    if isinstance(s, dict):
                        results.append(
                            RegistryServer(
                                name=str(s.get("name") or s.get("id") or ""),
                                description=s.get("description", ""),
                                author=str(s.get("author") or s.get("vendor") or ""),
                                registry="official",
                                repo_url=str(s.get("repository") or s.get("repo_url") or ""),
                                homepage=s.get("homepage", ""),
                            )
                        )
            else:
                logger.warning("Official MCP Registry returned %d", resp.status_code)
    except Exception as e:
        logger.warning("Official MCP Registry search failed: %s", e)

    return results


async def search_glama(
    query: str,
    *,
    page_size: int = 10,
) -> list[RegistryServer]:
    """Search Glama MCP server directory.

    Glama hosts MCP servers as a gateway — no local deployment needed.
    We list them for discovery but deploy our own containerized version.
    """
    results: list[RegistryServer] = []
    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://glama.ai/api/mcp/servers",
                params={"q": query, "limit": page_size},
            )
            if resp.status_code == 200:  # noqa: PLR2004
                data = resp.json()
                servers = data.get("servers", data) if isinstance(data, dict) else data
                for s in servers[:page_size]:
                    if isinstance(s, dict):
                        results.append(
                            RegistryServer(
                                name=s.get("name", ""),
                                description=s.get("description", ""),
                                author=str(s.get("author") or s.get("owner") or ""),
                                registry="glama",
                                repo_url=str(s.get("github_url") or s.get("repo_url") or ""),
                                homepage=(
                                    f"https://glama.ai/mcp/servers/"
                                    f"{s.get('owner', '')}/{s.get('name', '')}"
                                ),
                            )
                        )
    except Exception as e:
        logger.warning("Glama search failed: %s", e)

    return results


async def search_all_registries(
    query: str,
    *,
    smithery_api_key: str = "",
) -> dict[str, list[RegistryServer]]:
    """Search all registries in parallel. Returns results grouped by registry."""
    import asyncio

    smithery_task = asyncio.create_task(search_smithery(query, api_key=smithery_api_key))
    official_task = asyncio.create_task(search_official_registry(query))
    glama_task = asyncio.create_task(search_glama(query))

    smithery_results, official_results, glama_results = await asyncio.gather(
        smithery_task,
        official_task,
        glama_task,
        return_exceptions=True,
    )

    results: dict[str, list[RegistryServer]] = {}
    if isinstance(smithery_results, list):
        results["smithery"] = smithery_results
    else:
        results["smithery"] = []
        logger.warning("Smithery failed: %s", smithery_results)

    if isinstance(official_results, list):
        results["official"] = official_results
    else:
        results["official"] = []

    if isinstance(glama_results, list):
        results["glama"] = glama_results
    else:
        results["glama"] = []

    return results


# ── Security Scanner ─────────────────────────────────────────


async def scan_registry_server(
    server: RegistryServer,
    *,
    warden: Any = None,
) -> RegistryServer:
    """Scan an MCP server from a registry for security issues.

    Checks:
    1. Fetch README/description — run through Warden
    2. Check for known-malicious patterns (exec, eval, shell access)
    3. Check author reputation (verified, use count)
    4. Flag suspicious names or descriptions
    """
    flags: list[str] = []

    # Heuristic checks on metadata
    desc_lower = server.description.lower()
    name_lower = server.name.lower()

    # Suspicious patterns in name/description
    suspicious = [
        "unrestricted",
        "no restrictions",
        "bypass",
        "override",
        "full access",
        "admin mode",
        "shell access",
        "execute any",
        "unlimited",
        "no limits",
        "ignore safety",
        "developer mode",
    ]
    for pattern in suspicious:
        if pattern in desc_lower or pattern in name_lower:
            flags.append(f"suspicious_description: '{pattern}'")

    # Low trust signals
    if server.use_count < 10 and not server.verified:
        flags.append("low_adoption: <10 uses, unverified")

    # Author red flags
    if any(x in server.author.lower() for x in ["hack", "exploit", "crack", "bypass"]):
        flags.append(f"suspicious_author: {server.author}")

    # If we have a Warden, scan the description
    if warden and server.description:
        verdict = await warden.scan(server.description, "registry_scan")
        if not verdict.clean:
            flags.extend(f"warden:{f}" for f in verdict.flags)

    # Set scan status
    if not flags:
        server.scan_status = "clean"
    elif any("warden:" in f for f in flags):
        server.scan_status = "blocked"
    else:
        server.scan_status = "flagged"

    server.scan_flags = flags
    return server
