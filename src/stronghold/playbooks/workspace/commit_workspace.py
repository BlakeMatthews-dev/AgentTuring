"""commit_workspace playbook — commit + optional push, with dry_run preview."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection, NextAction
from stronghold.tools.workspace import WorkspaceManager

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "owner": {"type": "string"},
        "repo": {"type": "string"},
        "issue_number": {"type": "integer"},
        "message": {"type": "string", "description": "Commit message."},
        "push": {"type": "boolean", "default": True, "description": "Push after commit."},
    },
    "required": ["owner", "repo", "issue_number", "message"],
}


@playbook(
    "commit_workspace",
    description=(
        "Commit staged changes in a Mason workspace; optionally push. "
        "Supports dry_run to preview status + message without mutating."
    ),
    input_schema=_INPUT_SCHEMA,
    writes=True,
    next_actions_hint=("open_pull_request",),
)
async def commit_workspace(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    owner = inputs["owner"]
    repo = inputs["repo"]
    issue = inputs["issue_number"]
    message = inputs["message"]
    push = bool(inputs.get("push", True))
    dry_run = bool(inputs.get("dry_run", False))

    manager = WorkspaceManager()

    if dry_run:
        status_result = await manager.execute(
            {"action": "status", "owner": owner, "repo": repo, "issue_number": issue},
        )
        preview = ""
        if status_result.success:
            try:
                preview = json.dumps(json.loads(status_result.content), indent=2)
            except json.JSONDecodeError:
                preview = status_result.content
        return Brief(
            title=f"Dry-run: commit {owner}/{repo}#{issue}",
            summary=f"would commit '{message[:60]}' push={push}",
            sections=(
                BriefSection(
                    heading="Plan",
                    body=(
                        f"- message: {message}\n"
                        f"- push after commit: {push}\n"
                        f"- current status:\n```json\n{preview}\n```"
                    ),
                ),
            ),
            next_actions=(
                NextAction(
                    tool="commit_workspace",
                    args={
                        "owner": owner,
                        "repo": repo,
                        "issue_number": issue,
                        "message": message,
                        "push": push,
                    },
                    reason="execute the commit (dry_run=False)",
                ),
            ),
            source_calls=("workspace: status",),
        )

    commit_result = await manager.execute(
        {
            "action": "commit",
            "owner": owner,
            "repo": repo,
            "issue_number": issue,
            "message": message,
        },
    )
    if not commit_result.success:
        return Brief(
            title=f"commit_workspace failed in {owner}/{repo}#{issue}",
            summary=str(commit_result.error or "commit failed"),
            flags=("commit-error",),
        )

    calls = ["workspace: commit"]
    push_note = ""
    if push:
        push_result = await manager.execute(
            {
                "action": "push",
                "owner": owner,
                "repo": repo,
                "issue_number": issue,
            },
        )
        calls.append("workspace: push")
        push_note = (
            f"\n- push: {'ok' if push_result.success else 'FAILED — ' + str(push_result.error)}"
        )

    return Brief(
        title=f"Committed in {owner}/{repo}#{issue}",
        summary=f"message='{message[:60]}' push={push}",
        sections=(BriefSection(heading="Result", body=f"- message: {message}{push_note}"),),
        source_calls=tuple(calls),
    )


class CommitWorkspacePlaybook:
    @property
    def definition(self) -> Any:
        return commit_workspace._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await commit_workspace(inputs, ctx)
