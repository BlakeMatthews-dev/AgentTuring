"""MCP wire server: exposes Stronghold playbooks over the Model Context Protocol.

Builds an `mcp.server.Server` whose `list_tools` / `call_tool` handlers
delegate to `Container.playbook_registry`. Each playbook is surfaced as
an MCP Tool; calling a tool runs the playbook through its
`PlaybookToolExecutor` adapter so the same pre/post Warden + Sentinel
wrap applies.

Transports:
- stdio: see `stronghold.mcp_server.stdio.run_stdio_server`
- Streamable HTTP: Phase I will mount under `/mcp/v1/` (not in this module)

ADR-K8S-020 "MCP Server + Gateway + Orchestrator", ADR-K8S-024 transports.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from stronghold.mcp_server.capabilities import server_metadata

if TYPE_CHECKING:
    from stronghold.container import Container

logger = logging.getLogger("stronghold.mcp_server")

SERVER_NAME = "stronghold"


def build_mcp_server(container: Container) -> Server[Any]:
    """Construct an `mcp.Server` that exposes playbooks + catalog primitives."""
    meta = server_metadata()
    server: Server[Any] = Server(name=SERVER_NAME, version=meta.version)

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def _list_tools() -> list[Tool]:
        return [_definition_to_tool(defn) for defn in container.playbook_registry.list_all()]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        playbook = container.playbook_registry.get(name)
        if playbook is None:
            return [TextContent(type="text", text=f"Unknown playbook: {name}")]
        adapter = _build_adapter(container, playbook)
        result = await adapter.execute(arguments or {})
        if not result.success:
            error_msg = result.error or "Playbook failed without error message"
            return [TextContent(type="text", text=f"Error: {error_msg}")]
        return [TextContent(type="text", text=result.content)]

    return server


def _definition_to_tool(defn: Any) -> Tool:
    description = defn.description
    if defn.writes:
        description = f"{description}\n\n(writes=True — supports dry_run)"
    return Tool(
        name=defn.name,
        description=description,
        inputSchema=dict(defn.input_schema),
    )


def _build_adapter(container: Container, playbook: Any) -> Any:
    from stronghold.playbooks.executor_adapter import (  # noqa: PLC0415
        PlaybookAdapterDeps,
        PlaybookToolExecutor,
    )

    deps = PlaybookAdapterDeps(
        llm=container.llm,
        warden=container.warden,
        tracer=container.tracer,
    )
    return PlaybookToolExecutor(playbook, deps)
