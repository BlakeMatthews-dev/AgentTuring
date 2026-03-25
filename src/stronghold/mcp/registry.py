"""MCP server registry: tracks all managed and remote MCP servers.

Supports the full pipeline:
1. Register from image (pre-built) or repo_url (clone+build)
2. Security scan (Warden on README/SOUL, code scan)
3. Deploy to K8s with auth proxy sidecar
4. Discover tools via MCP protocol
5. Register tools in Stronghold tool registry
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.mcp.types import (
    MCPDiscoveredTool,
    MCPServer,
    MCPServerSpec,
    MCPServerStatus,
    MCPSourceType,
)

logger = logging.getLogger("stronghold.mcp.registry")

# Catalog of well-known MCP servers (pre-vetted, official images)
KNOWN_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "github": {
        "image": "ghcr.io/modelcontextprotocol/server-github:latest",
        "description": "GitHub integration — repos, PRs, issues, actions",
        "author": "Anthropic (official)",
        "port": 3000,
        "trust_tier": "t2",
        "secrets": {"GITHUB_PERSONAL_ACCESS_TOKEN": "github-pat:token"},
        "known_tools": [
            MCPDiscoveredTool("create_or_update_file", "Create or update a file in a repository"),
            MCPDiscoveredTool("search_repositories", "Search GitHub repositories"),
            MCPDiscoveredTool("create_issue", "Create a new issue in a repository"),
            MCPDiscoveredTool("create_pull_request", "Create a new pull request"),
            MCPDiscoveredTool("list_issues", "List issues in a repository"),
            MCPDiscoveredTool("get_file_contents", "Get contents of a file from a repository"),
            MCPDiscoveredTool("push_files", "Push multiple files to a repository"),
            MCPDiscoveredTool("fork_repository", "Fork a repository"),
        ],
    },
    "filesystem": {
        "image": "ghcr.io/modelcontextprotocol/server-filesystem:latest",
        "description": "Sandboxed file system access via MCP",
        "author": "Anthropic (official)",
        "port": 3000,
        "trust_tier": "t2",
        "known_tools": [
            MCPDiscoveredTool("read_file", "Read contents of a file"),
            MCPDiscoveredTool("write_file", "Write contents to a file"),
            MCPDiscoveredTool("list_directory", "List directory contents"),
            MCPDiscoveredTool("create_directory", "Create a new directory"),
            MCPDiscoveredTool("move_file", "Move or rename a file"),
            MCPDiscoveredTool("search_files", "Search for files matching a pattern"),
            MCPDiscoveredTool("get_file_info", "Get metadata about a file"),
        ],
    },
    "postgres": {
        "image": "ghcr.io/modelcontextprotocol/server-postgres:latest",
        "description": "PostgreSQL database queries via MCP",
        "author": "Anthropic (official)",
        "port": 3000,
        "trust_tier": "t2",
        "secrets": {"DATABASE_URL": "postgres-creds:url"},
        "known_tools": [
            MCPDiscoveredTool("query", "Execute a read-only SQL query"),
            MCPDiscoveredTool("list_tables", "List all tables in the database"),
            MCPDiscoveredTool("describe_table", "Get schema for a table"),
        ],
    },
    "slack": {
        "image": "ghcr.io/modelcontextprotocol/server-slack:latest",
        "description": "Slack workspace integration via MCP",
        "author": "Anthropic (official)",
        "port": 3000,
        "trust_tier": "t2",
        "secrets": {"SLACK_BOT_TOKEN": "slack-token:bot-token"},
        "known_tools": [
            MCPDiscoveredTool("send_message", "Send a message to a Slack channel"),
            MCPDiscoveredTool("list_channels", "List available Slack channels"),
            MCPDiscoveredTool("search_messages", "Search messages in Slack"),
        ],
    },
}


class MCPRegistry:
    """In-memory registry of MCP servers."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}

    # C12: Allowed image registries — only deploy from trusted sources
    ALLOWED_IMAGE_PREFIXES: tuple[str, ...] = (
        "ghcr.io/modelcontextprotocol/",
        "ghcr.io/anthropics/",
        "docker.io/library/",
        "mcr.microsoft.com/",
    )

    def register(
        self,
        spec: MCPServerSpec,
        *,
        source_type: MCPSourceType = MCPSourceType.MANAGED,
        org_id: str = "",
    ) -> MCPServer:
        """Register a new MCP server (does not deploy yet).

        C12: Validates image is from an allowed registry to prevent
        deployment of arbitrary/malicious container images.
        """
        # Validate image registry
        if not any(spec.image.startswith(prefix) for prefix in self.ALLOWED_IMAGE_PREFIXES):
            msg = (
                f"Image {spec.image!r} is not from an allowed registry. "
                f"Allowed prefixes: {self.ALLOWED_IMAGE_PREFIXES}"
            )
            raise ValueError(msg)

        server = MCPServer(
            spec=spec,
            source_type=source_type,
            org_id=org_id,
        )

        # If it's a known server, attach pre-discovered tools
        known = KNOWN_MCP_SERVERS.get(spec.name)
        if known:
            server.tools = known.get("known_tools", [])

        self._servers[spec.name] = server
        logger.info("Registered MCP server: %s (%s)", spec.name, spec.image)
        return server

    def register_from_catalog(
        self,
        name: str,
        *,
        org_id: str = "",
        env_overrides: dict[str, str] | None = None,
    ) -> MCPServer:
        """Register a well-known MCP server from the catalog."""
        catalog_entry = KNOWN_MCP_SERVERS.get(name)
        if not catalog_entry:
            msg = f"Unknown MCP server: {name}. Available: {list(KNOWN_MCP_SERVERS.keys())}"
            raise ValueError(msg)

        spec = MCPServerSpec(
            name=name,
            image=catalog_entry["image"],
            description=catalog_entry.get("description", ""),
            author=catalog_entry.get("author", ""),
            port=catalog_entry.get("port", 3000),
            trust_tier=catalog_entry.get("trust_tier", "t3"),
            secrets=catalog_entry.get("secrets", {}),
            env=env_overrides or {},
        )
        return self.register(spec, org_id=org_id)

    def get(self, name: str) -> MCPServer | None:
        """Get a registered MCP server by name."""
        return self._servers.get(name)

    def list_all(self, *, org_id: str = "") -> list[MCPServer]:
        """List all registered servers, optionally filtered by org."""
        servers = list(self._servers.values())
        if org_id:
            servers = [s for s in servers if s.org_id == org_id or not s.org_id]
        return servers

    def remove(self, name: str) -> MCPServer | None:
        """Remove a server from the registry."""
        return self._servers.pop(name, None)

    def catalog(self) -> list[dict[str, Any]]:
        """List available MCP servers from the built-in catalog."""
        result = []
        for name, entry in KNOWN_MCP_SERVERS.items():
            installed = name in self._servers
            status = self._servers[name].status.value if installed else "available"
            result.append(
                {
                    "name": name,
                    "image": entry["image"],
                    "description": entry.get("description", ""),
                    "author": entry.get("author", ""),
                    "trust_tier": entry.get("trust_tier", "t3"),
                    "tool_count": len(entry.get("known_tools", [])),
                    "installed": installed,
                    "status": status,
                }
            )
        return result

    def update_status(self, name: str, status: MCPServerStatus, error: str = "") -> None:
        """Update server status (called by deployer)."""
        server = self._servers.get(name)
        if server:
            server.status = status
            server.error = error
