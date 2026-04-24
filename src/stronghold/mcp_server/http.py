"""Streamable HTTP transport (ADR-K8S-024) for the Stronghold MCP server.

Mounts `/mcp/v1/` on the main FastAPI app. Uses the MCP SDK's
StreamableHTTPSessionManager, which implements the 2025-03-26 single-
endpoint transport (`Mcp-Session-Id` header, JSON-RPC batch, server-
chosen SSE streaming). Deprecated HTTP+SSE dual-endpoint is not
supported.

Lifecycle: the session manager is an async context manager; callers
(src/stronghold/api/app.py lifespan) enter it once at startup and exit
at shutdown.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from stronghold.mcp_server.app import build_mcp_server

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

    from stronghold.container import Container

logger = logging.getLogger("stronghold.mcp_server.http")

MCP_HTTP_PREFIX = "/mcp/v1"


@asynccontextmanager
async def lifespan_streamable_http(
    container: Container,
) -> AsyncIterator[StreamableHTTPSessionManager]:
    """Startup/shutdown context for the Streamable HTTP session manager.

    Yielded manager is used by ``mount_streamable_http`` below.
    """
    server = build_mcp_server(container)
    manager = StreamableHTTPSessionManager(app=server)
    async with manager.run():
        logger.info("Stronghold MCP StreamableHTTP transport started on %s", MCP_HTTP_PREFIX)
        try:
            yield manager
        finally:
            logger.info("Stronghold MCP StreamableHTTP transport stopping")


def mount_streamable_http(
    app: FastAPI,
    manager: StreamableHTTPSessionManager,
) -> None:
    """Mount the MCP StreamableHTTP handler under /mcp/v1/ on a FastAPI app.

    The SDK's handler follows the ASGI (scope, receive, send) contract so
    FastAPI's ``app.mount()`` fits it directly — no middleware adapter
    needed.
    """

    async def _app(scope: Any, receive: Any, send: Any) -> None:
        await manager.handle_request(scope, receive, send)

    app.mount(MCP_HTTP_PREFIX, _app)
    logger.info("Mounted MCP Streamable HTTP handler at %s", MCP_HTTP_PREFIX)
