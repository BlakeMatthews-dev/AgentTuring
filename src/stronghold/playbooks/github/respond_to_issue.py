"""respond_to_issue playbook — comment, close, reopen, or label in one call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.playbooks.github._client import GitHubClient, parse_issue_url, parse_pr_url

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_ACTIONS = ("comment", "close", "reopen", "label")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "GitHub issue or PR URL.",
        },
        "action": {"type": "string", "enum": list(_ACTIONS), "default": "comment"},
        "message": {"type": "string", "default": ""},
        "labels": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["url", "action"],
}


@playbook(
    "respond_to_issue",
    description="Take an action on a GitHub issue or PR: comment, close, reopen, or label.",
    input_schema=_INPUT_SCHEMA,
    writes=True,
)
async def respond_to_issue(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    url = inputs["url"]
    action = inputs.get("action", "comment")
    message = inputs.get("message", "")
    labels = inputs.get("labels") or []
    dry_run = bool(inputs.get("dry_run", False))

    if action not in _ACTIONS:
        raise ValueError(f"Unknown action: {action}. Use one of {_ACTIONS}.")

    owner: str
    repo_name: str
    number: int
    try:
        issue_ref = parse_issue_url(url)
        owner, repo_name, number = issue_ref.owner, issue_ref.repo, issue_ref.number
    except ValueError:
        pr_ref = parse_pr_url(url)
        owner, repo_name, number = pr_ref.owner, pr_ref.repo, pr_ref.number

    plan = f"- action: **{action}** on {owner}/{repo_name}#{number}"
    if action == "comment":
        plan += f"\n- message length: {len(message)} chars"
    if action == "label":
        plan += f"\n- labels: {labels}"

    if dry_run:
        return Brief(
            title=f"Dry-run: {action} on #{number}",
            summary=f"would {action} #{number} in {owner}/{repo_name}",
            sections=(BriefSection(heading="Plan", body=plan),),
            source_calls=("(dry-run — no upstream calls)",),
        )

    client = GitHubClient()
    if action == "comment":
        if not message:
            raise ValueError("action=comment requires non-empty message")
        resp = await client.request(
            "POST",
            f"/repos/{owner}/{repo_name}/issues/{number}/comments",
            json_body={"body": message},
        )
    elif action == "close":
        resp = await client.request(
            "PATCH",
            f"/repos/{owner}/{repo_name}/issues/{number}",
            json_body={"state": "closed"},
        )
    elif action == "reopen":
        resp = await client.request(
            "PATCH",
            f"/repos/{owner}/{repo_name}/issues/{number}",
            json_body={"state": "open"},
        )
    else:  # label
        if not labels:
            raise ValueError("action=label requires non-empty labels")
        resp = await client.request(
            "POST",
            f"/repos/{owner}/{repo_name}/issues/{number}/labels",
            json_body={"labels": labels},
        )

    if resp.status_code >= 400:
        return Brief(
            title=f"Failed to {action} #{number}",
            summary=f"GitHub {resp.status_code}: {resp.text[:200]}",
            flags=(f"github-{resp.status_code}",),
        )
    return Brief(
        title=f"{action}: #{number} in {owner}/{repo_name}",
        summary=f"GitHub {resp.status_code}",
        sections=(BriefSection(heading="Action", body=plan),),
        source_calls=(
            f"{resp.request.method} /repos/{owner}/{repo_name}/issues/{number}"
            + ("/comments" if action == "comment" else "/labels" if action == "label" else ""),
        ),
    )


class RespondToIssuePlaybook:
    @property
    def definition(self) -> Any:
        return respond_to_issue._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await respond_to_issue(inputs, ctx)
