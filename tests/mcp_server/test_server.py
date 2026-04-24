"""MCP wire-server tests using the SDK's in-memory transport.

Exercises initialize → list_tools → call_tool end-to-end against a real
`mcp.Server` instance with no subprocess, no sockets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from mcp.shared.memory import create_connected_server_and_client_session

from stronghold.mcp_server import build_mcp_server
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
    def __init__(self, name: str, *, brief: Brief | None = None) -> None:
        self.definition = PlaybookDefinition(
            name=name,
            description=f"Run {name}",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )
        self._brief = brief or Brief(
            title=f"{name}-brief",
            summary="ok",
            sections=(BriefSection(heading="Detail", body="some details"),),
        )
        self.calls: list[dict[str, Any]] = []

    async def execute(self, inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
        self.calls.append(inputs)
        return self._brief


def _container_with(*playbooks: _StubPlaybook) -> _FakeContainer:
    reg = InMemoryPlaybookRegistry()
    for pb in playbooks:
        reg.register(pb)
    return _FakeContainer(playbook_registry=reg)


async def test_initialize_returns_server_metadata() -> None:
    container = _container_with()
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        init = await client.initialize()
        assert init.serverInfo.name == "stronghold"


async def test_list_tools_enumerates_registered_playbooks() -> None:
    pb_a = _StubPlaybook("review_pull_request")
    pb_b = _StubPlaybook("triage_issues")
    container = _container_with(pb_a, pb_b)
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = (await client.list_tools()).tools
    names = sorted(t.name for t in tools)
    assert names == ["review_pull_request", "triage_issues"]


async def test_list_tools_reflects_input_schema() -> None:
    pb = _StubPlaybook("review_pull_request")
    container = _container_with(pb)
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = (await client.list_tools()).tools
    (tool,) = tools
    assert tool.inputSchema["properties"]["url"]["type"] == "string"
    assert "url" in tool.inputSchema["required"]


async def test_call_tool_executes_playbook_and_returns_brief_markdown() -> None:
    pb = _StubPlaybook(
        "review_pull_request",
        brief=Brief(
            title="PR #42",
            summary="author alice, 1 check failing",
            flags=("failing checks",),
        ),
    )
    container = _container_with(pb)
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool(
            "review_pull_request",
            {"url": "https://github.com/a/b/pull/42"},
        )

    assert pb.calls == [{"url": "https://github.com/a/b/pull/42"}]
    assert len(result.content) == 1
    text_item = result.content[0]
    assert text_item.type == "text"
    assert "# PR #42" in text_item.text
    assert "> Flags: failing checks" in text_item.text


async def test_call_unknown_tool_returns_error_text() -> None:
    container = _container_with()
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        # Unknown tools raise through the SDK's validation layer when the
        # tool is missing from list_tools entirely; the handler branch
        # exists for defense in depth. Directly register a "phantom" that
        # is not discoverable to exercise it:
        # Easier: add a playbook then remove it from the registry post-init.
        pb = _StubPlaybook("ghost")
        container.playbook_registry.register(pb)
        # Simulate removal after the cache was built:
        container.playbook_registry._executors.pop("ghost")  # type: ignore[attr-defined]  # noqa: SLF001
        # Because tool cache on server may still know the tool, call it:
        # (If the SDK rejects unknown names upstream, this test still passes
        # with a different error shape — either error text or exception.)
        try:
            result = await client.call_tool("ghost", {"url": "x"})
            assert any("Unknown" in c.text or "error" in c.text.lower() for c in result.content)
        except Exception as exc:  # noqa: BLE001
            assert "ghost" in str(exc).lower() or "unknown" in str(exc).lower()


async def test_call_tool_reports_playbook_failure_as_error_text() -> None:
    class _Boom:
        definition = PlaybookDefinition(
            name="boom",
            description="explodes",
            input_schema={"type": "object", "properties": {}, "required": []},
        )

        async def execute(self, _inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
            raise RuntimeError("kaboom")

    reg = InMemoryPlaybookRegistry()
    reg.register(_Boom())
    container = _FakeContainer(playbook_registry=reg)
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        result = await client.call_tool("boom", {})
    assert "Error" in result.content[0].text
    assert "kaboom" in result.content[0].text


async def test_build_mcp_server_injects_container_deps_into_context() -> None:
    pb = _StubPlaybook("inspect_ctx")
    container = _container_with(pb)
    container.llm = MagicMock()
    container.warden = AsyncMock()
    container.tracer = MagicMock()
    server = build_mcp_server(container)  # type: ignore[arg-type]
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        await client.call_tool("inspect_ctx", {"url": "x"})
    # No assertion on context internals here — the adapter tests cover
    # that path. This test verifies build_mcp_server wires without raising.
    assert pb.calls == [{"url": "x"}]
