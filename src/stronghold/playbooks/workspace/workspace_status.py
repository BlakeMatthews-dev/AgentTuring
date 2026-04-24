"""workspace_status playbook — snapshot a Mason workspace (branch, dirty files, ahead/behind)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.tools.workspace import WorkspaceManager

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"},
        "issue_number": {"type": "integer"},
    },
    "required": ["owner", "repo", "issue_number"],
}


@playbook(
    "workspace_status",
    description=(
        "Inspect a Mason workspace for a given issue: branch, dirty files, "
        "and commits ahead/behind main. Does not mutate."
    ),
    input_schema=_INPUT_SCHEMA,
    next_actions_hint=("commit_workspace",),
)
async def workspace_status(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    owner = inputs["owner"]
    repo = inputs["repo"]
    issue = inputs["issue_number"]
    manager = WorkspaceManager()
    result = await manager.execute(
        {"action": "status", "owner": owner, "repo": repo, "issue_number": issue},
    )
    if not result.success:
        return Brief(
            title=f"workspace_status failed for {owner}/{repo}#{issue}",
            summary=str(result.error or "unknown error"),
            flags=("workspace-error",),
        )
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError:
        payload = {"raw": result.content}
    flags: list[str] = []
    if payload.get("dirty"):
        flags.append("uncommitted changes")
    if int(payload.get("ahead", 0) or 0) > 0:
        flags.append(f"{payload['ahead']} commit(s) ahead of base")
    body = (
        f"- branch: `{payload.get('branch', '?')}`\n"
        f"- worktree: `{payload.get('worktree', '?')}`\n"
        f"- ahead: {payload.get('ahead', 0)}\n"
        f"- behind: {payload.get('behind', 0)}\n"
        f"- dirty: {payload.get('dirty', False)}\n"
    )
    return Brief(
        title=f"Workspace status: {owner}/{repo}#{issue}",
        summary=f"branch={payload.get('branch', '?')} dirty={payload.get('dirty', False)}",
        sections=(BriefSection(heading="State", body=body),),
        flags=tuple(flags),
        source_calls=("workspace: status",),
    )


class WorkspaceStatusPlaybook:
    @property
    def definition(self) -> Any:
        return workspace_status._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await workspace_status(inputs, ctx)
