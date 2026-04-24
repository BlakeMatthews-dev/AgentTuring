"""MCP wire server (ADR-K8S-020): Stronghold as MCP server + gateway.

`build_mcp_server(container)` returns an `mcp.server.Server` surfacing
playbooks from `container.playbook_registry`. Transports live alongside:
- `stdio.run_stdio_server` (local clients)
- Streamable HTTP router (Phase I)
"""

from __future__ import annotations

from stronghold.mcp_server.app import SERVER_NAME, build_mcp_server
from stronghold.mcp_server.capabilities import (
    PROTOCOL_VERSION,
    SERVER_VERSION,
    ServerMetadata,
    server_metadata,
)

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "ServerMetadata",
    "build_mcp_server",
    "server_metadata",
]
