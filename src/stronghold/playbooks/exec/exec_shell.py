"""exec_shell playbook — sandboxed shell with dry_run preview.

Wraps ShellExecutor (tools/shell_exec.py:134) and surfaces a Brief that
explains the command before (dry_run) or after (live) execution. All
existing shell-injection protections apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.tools.shell_exec import ShellExecutor

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to execute."},
        "workspace": {"type": "string", "description": "Workspace directory."},
    },
    "required": ["command", "workspace"],
}


@playbook(
    "exec_shell",
    description="Run a sandboxed shell command. Supports dry_run preview.",
    input_schema=_INPUT_SCHEMA,
    writes=True,
)
async def exec_shell(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    command = str(inputs.get("command", "")).strip()
    workspace = str(inputs.get("workspace", "")).strip()
    dry_run = bool(inputs.get("dry_run", False))

    if not command:
        raise ValueError("exec_shell requires non-empty command")

    plan = f"- command: `{command}`\n- workspace: {workspace or '(not set)'}"
    if dry_run:
        return Brief(
            title="Dry-run: exec_shell",
            summary=f"would run `{command}` in {workspace}",
            sections=(BriefSection(heading="Plan", body=plan),),
            source_calls=("(dry-run — no command executed)",),
        )

    shell = ShellExecutor()
    result = await shell.execute({"command": command, "workspace": workspace})

    out = (result.content or "").strip()
    if len(out) > 3000:
        out = out[:3000] + "\n... (truncated)"

    flags = () if result.success else (result.error or "shell failed",)
    return Brief(
        title=f"exec_shell: {command[:60]}",
        summary=("succeeded" if result.success else f"failed: {result.error}"),
        sections=(
            BriefSection(heading="Command", body=plan),
            BriefSection(heading="Output", body=f"```\n{out or '(empty)'}\n```"),
        ),
        flags=flags,
        source_calls=(f"shell: {command}",),
    )


class ExecShellPlaybook:
    @property
    def definition(self) -> Any:
        return exec_shell._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await exec_shell(inputs, ctx)
