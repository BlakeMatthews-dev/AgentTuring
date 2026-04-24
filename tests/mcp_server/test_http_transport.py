"""Streamable HTTP transport: end-to-end initialize/list_tools/call_tool.

Mounts the MCP Streamable HTTP handler on a FastAPI app and drives it
with the MCP SDK's streamablehttp_client. No real network — httpx is
routed in-memory through the ASGI transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from stronghold.mcp_server.http import lifespan_streamable_http, mount_streamable_http
from stronghold.playbooks.base import PlaybookDefinition
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.playbooks.registry import InMemoryPlaybookRegistry

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext


@dataclass
class _FakeContainer:
    playbook_registry: InMemoryPlaybookRegistry
    llm: Any = None
    warden: Any = None
    tracer: Any = None


class _StubPlaybook:
    def __init__(self, name: str) -> None:
        self.definition = PlaybookDefinition(
            name=name,
            description=f"Run {name}",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": [],
            },
        )

    async def execute(self, _inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
        return Brief(
            title=f"{self.definition.name}-brief",
            summary="hello from streamable http",
            sections=(BriefSection(heading="Note", body="served over /mcp/v1"),),
        )


async def test_streamable_http_initialize_list_and_call() -> None:
    reg = InMemoryPlaybookRegistry()
    reg.register(_StubPlaybook("hello_mcp"))
    container = _FakeContainer(playbook_registry=reg)
    app = FastAPI()

    async with lifespan_streamable_http(container) as manager:  # type: ignore[arg-type]
        mount_streamable_http(app, manager)
        transport = httpx.ASGITransport(app=app)

        def _factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.setdefault("base_url", "http://test")
            kwargs["transport"] = transport
            return httpx.AsyncClient(**kwargs)

        url = "http://test/mcp/v1/"
        async with (
            streamablehttp_client(url, httpx_client_factory=_factory) as (  # type: ignore[arg-type]
                read_stream,
                write_stream,
                _session_id,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            init = await session.initialize()
            assert init.serverInfo.name == "stronghold"

            tools = (await session.list_tools()).tools
            assert [t.name for t in tools] == ["hello_mcp"]

            result = await session.call_tool("hello_mcp", {"url": "x"})
            assert len(result.content) == 1
            text = result.content[0].text  # type: ignore[attr-defined]
            assert "hello from streamable http" in text
            assert "/mcp/v1" in text
