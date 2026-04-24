"""PlaybookToolExecutor adapter: Brief → ToolResult round-trip, error paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import PlaybookDefinition
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.playbooks.executor_adapter import PlaybookAdapterDeps, PlaybookToolExecutor
from stronghold.types.auth import SYSTEM_AUTH, AuthContext

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext


class _StubPlaybook:
    def __init__(self, brief: Brief | None = None, *, raises: Exception | None = None) -> None:
        self.definition = PlaybookDefinition(name="stub", description="stub")
        self._brief = brief or Brief(title="stub-ok", summary="done")
        self._raises = raises
        self.calls: list[tuple[dict[str, Any], PlaybookContext]] = []

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        self.calls.append((inputs, ctx))
        if self._raises is not None:
            raise self._raises
        return self._brief


async def test_adapter_wraps_brief_into_tool_result() -> None:
    pb = _StubPlaybook()
    adapter = PlaybookToolExecutor(pb, PlaybookAdapterDeps())
    result = await adapter.execute({"arg": 1})
    assert result.success is True
    assert result.error is None
    assert "# stub-ok" in result.content
    assert "done" in result.content


async def test_adapter_forwards_inputs_and_context() -> None:
    pb = _StubPlaybook()
    adapter = PlaybookToolExecutor(pb, PlaybookAdapterDeps())
    await adapter.execute({"url": "x"})
    inputs, ctx = pb.calls[0]
    assert inputs == {"url": "x"}
    assert ctx.auth is SYSTEM_AUTH


async def test_adapter_uses_custom_auth_factory() -> None:
    pb = _StubPlaybook()
    custom = AuthContext(user_id="alice", org_id="acme", team_id="platform")
    adapter = PlaybookToolExecutor(
        pb,
        PlaybookAdapterDeps(),
        auth_factory=lambda: custom,
    )
    await adapter.execute({})
    assert pb.calls[0][1].auth is custom


async def test_adapter_copies_flags_to_warden_flags() -> None:
    pb = _StubPlaybook(Brief(title="t", flags=("risky", "stale")))
    adapter = PlaybookToolExecutor(pb, PlaybookAdapterDeps())
    result = await adapter.execute({})
    assert result.warden_flags == ("risky", "stale")


async def test_adapter_handles_playbook_exceptions_as_failure() -> None:
    pb = _StubPlaybook(raises=RuntimeError("boom"))
    adapter = PlaybookToolExecutor(pb, PlaybookAdapterDeps())
    result = await adapter.execute({})
    assert result.success is False
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert "boom" in result.error


async def test_adapter_rejects_non_brief_return() -> None:
    class _BadPlaybook:
        definition = PlaybookDefinition(name="bad", description="bad")

        async def execute(self, _inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
            return "not a brief"  # type: ignore[return-value]

    adapter = PlaybookToolExecutor(_BadPlaybook(), PlaybookAdapterDeps())
    result = await adapter.execute({})
    assert result.success is False
    assert result.error is not None
    assert "expected Brief" in result.error


async def test_adapter_uses_large_budget_when_configured() -> None:
    big_body = "x" * 9000
    brief = Brief(
        title="big",
        summary="large",
        sections=(BriefSection(heading="dump", body=big_body),),
    )
    pb = _StubPlaybook(brief)
    small = PlaybookToolExecutor(pb, PlaybookAdapterDeps(allow_large_briefs=False))
    large = PlaybookToolExecutor(pb, PlaybookAdapterDeps(allow_large_briefs=True))
    small_result = await small.execute({})
    large_result = await large.execute({})
    assert len(large_result.content) > len(small_result.content)


def test_adapter_exposes_definition_and_name() -> None:
    pb = _StubPlaybook()
    adapter = PlaybookToolExecutor(pb, PlaybookAdapterDeps())
    assert adapter.name == "stub"
    assert adapter.definition is pb.definition
