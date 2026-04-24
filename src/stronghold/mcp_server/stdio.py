"""Stdio transport runner for the Stronghold MCP server.

Used by local MCP clients (operator `kubectl exec`, dev workflows, the
`scripts/stronghold-mcp-stdio` CLI). External clients go through the
Streamable HTTP transport (Phase I).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.server.stdio import stdio_server

from stronghold.mcp_server.app import build_mcp_server

if TYPE_CHECKING:
    from stronghold.container import Container

logger = logging.getLogger("stronghold.mcp_server.stdio")


async def run_stdio_server(container: Container) -> None:
    server = build_mcp_server(container)
    init_opts = server.create_initialization_options()
    logger.info("Starting Stronghold MCP server over stdio")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_opts)
