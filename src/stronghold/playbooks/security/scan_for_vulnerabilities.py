"""scan_for_vulnerabilities playbook — composed security scan over a workspace.

Runs semgrep + bandit + trufflehog concurrently via the existing
ShellExecutor and summarizes findings into a single Brief. One tool call
replaces three separate invocations the agent would otherwise chain.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.tools.shell_exec import ShellExecutor

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext
    from stronghold.types.tool import ToolResult

logger = logging.getLogger("stronghold.playbooks.security.scan")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Workspace-relative path to scan (default: '.').",
            "default": ".",
        },
        "scanners": {
            "type": "array",
            "items": {"type": "string", "enum": ["semgrep", "bandit", "trufflehog"]},
            "description": "Subset of scanners to run (default: all three).",
        },
    },
    "required": [],
}

_ALL_SCANNERS = ("semgrep", "bandit", "trufflehog")


@playbook(
    "scan_for_vulnerabilities",
    description="Run semgrep + bandit + trufflehog in parallel and summarize findings.",
    input_schema=_INPUT_SCHEMA,
)
async def scan_for_vulnerabilities(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    path = str(inputs.get("path", ".")).strip() or "."
    requested = tuple(inputs.get("scanners") or _ALL_SCANNERS)
    scanners = tuple(s for s in requested if s in _ALL_SCANNERS)
    if not scanners:
        raise ValueError(f"No valid scanners in {requested!r}")

    shell = ShellExecutor()
    results = await asyncio.gather(*[_run_scan(shell, s, path) for s in scanners])

    sections: list[BriefSection] = []
    flags: list[str] = []
    total_findings = 0
    for scanner, result in zip(scanners, results, strict=True):
        count, section = _summarize(scanner, result)
        total_findings += count
        sections.append(section)
        if count > 0:
            flags.append(f"{scanner}: {count} findings")

    summary = (
        f"ran {', '.join(scanners)} on {path} — "
        f"{total_findings} finding{'s' if total_findings != 1 else ''}"
    )
    return Brief(
        title=f"Security scan: {path}",
        summary=summary,
        sections=tuple(sections),
        flags=tuple(flags),
        source_calls=tuple(f"shell: {_scanner_cmd(s, path)}" for s in scanners),
    )


async def _run_scan(shell: ShellExecutor, scanner: str, path: str) -> ToolResult:
    # ShellExecutor requires `workspace` + `command` keys. For tests, a fake
    # shell is substituted; production wiring will pass the tenant workspace.
    return await shell.execute(
        {"command": _scanner_cmd(scanner, path), "workspace": "."},
    )


def _scanner_cmd(scanner: str, path: str) -> str:
    safe = path.replace("'", "").replace("..", "").strip() or "."
    if scanner == "semgrep":
        return f"semgrep --config=auto --json {safe}"
    if scanner == "bandit":
        return f"bandit -r {safe} -f json -ll"
    return f"trufflehog filesystem {safe} --json --no-update"


def _summarize(scanner: str, result: ToolResult) -> tuple[int, BriefSection]:
    if not result.success:
        return (
            0,
            BriefSection(
                heading=f"{scanner} (error)",
                body=f"```\n{result.error or 'command failed'}\n```",
            ),
        )
    findings = _count_findings(scanner, result.content)
    snippet = result.content.strip()
    if len(snippet) > 2000:
        snippet = snippet[:2000] + "\n... (truncated)"
    return (
        findings,
        BriefSection(
            heading=f"{scanner} — {findings} finding(s)",
            body=f"```json\n{snippet}\n```" if snippet else "_(no output)_",
        ),
    )


def _count_findings(scanner: str, content: str) -> int:
    if not content.strip():
        return 0
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return len([ln for ln in content.splitlines() if ln.strip()])
    if scanner == "semgrep" and isinstance(data, dict):
        results = data.get("results", [])
        return len(results) if isinstance(results, list) else 0
    if scanner == "bandit" and isinstance(data, dict):
        results = data.get("results", [])
        return len(results) if isinstance(results, list) else 0
    if scanner == "trufflehog":
        return 1 if isinstance(data, dict) else (len(data) if isinstance(data, list) else 0)
    return 0


class ScanForVulnerabilitiesPlaybook:
    @property
    def definition(self) -> Any:
        return scan_for_vulnerabilities._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await scan_for_vulnerabilities(inputs, ctx)
