"""scan_for_vulnerabilities playbook: scanner composition + summarization."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.playbooks.security.scan_for_vulnerabilities import (
    ScanForVulnerabilitiesPlaybook,
    scan_for_vulnerabilities,
)
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.tool import ToolResult


class _FakeShell:
    """Stub in place of ShellExecutor; returns canned responses per scanner."""

    def __init__(self, responses: dict[str, ToolResult]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        command = arguments["command"]
        for prefix, result in self._responses.items():
            if command.startswith(prefix):
                return result
        return ToolResult(success=False, error=f"no canned response for: {command}")


def _ctx() -> PlaybookContext:
    return PlaybookContext(auth=SYSTEM_AUTH)


async def test_scan_runs_all_three_scanners_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(
        {
            "semgrep": ToolResult(content='{"results": [{"id": 1}, {"id": 2}]}', success=True),
            "bandit": ToolResult(content='{"results": [{"id": "B101"}]}', success=True),
            "trufflehog": ToolResult(content="", success=True),
        }
    )
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.security.scan_for_vulnerabilities"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await scan_for_vulnerabilities({"path": "src/"}, _ctx())

    assert "semgrep: 2 findings" in brief.flags
    assert "bandit: 1 findings" in brief.flags
    assert len(brief.sections) == 3
    assert "3 findings" in brief.summary
    # Verify all three scanners were invoked
    commands = [c["command"] for c in fake.calls]
    assert any(c.startswith("semgrep") for c in commands)
    assert any(c.startswith("bandit") for c in commands)
    assert any(c.startswith("trufflehog") for c in commands)


async def test_scan_subset_when_scanners_specified(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(
        {"semgrep": ToolResult(content='{"results": []}', success=True)},
    )
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.security.scan_for_vulnerabilities"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await scan_for_vulnerabilities({"scanners": ["semgrep"]}, _ctx())

    assert len(brief.sections) == 1
    assert "semgrep" in brief.sections[0].heading
    assert len(fake.calls) == 1


async def test_scan_rejects_invalid_scanner_list() -> None:
    with pytest.raises(ValueError, match="No valid scanners"):
        await scan_for_vulnerabilities({"scanners": ["unknown"]}, _ctx())


async def test_scanner_error_surfaces_as_section(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(
        {"semgrep": ToolResult(success=False, error="semgrep not installed")},
    )
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.security.scan_for_vulnerabilities"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await scan_for_vulnerabilities({"scanners": ["semgrep"]}, _ctx())
    assert "(error)" in brief.sections[0].heading
    assert "not installed" in brief.sections[0].body


async def test_playbook_class_matches_function(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell({"semgrep": ToolResult(content="{}", success=True)})
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.security.scan_for_vulnerabilities"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    pb = ScanForVulnerabilitiesPlaybook()
    assert pb.definition.name == "scan_for_vulnerabilities"
    brief = await pb.execute({"scanners": ["semgrep"]}, _ctx())
    assert brief.title.startswith("Security scan")
