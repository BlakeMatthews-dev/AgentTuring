"""open_pull_request playbook — create a branch (if needed) and open a PR.

Writes. `dry_run=True` renders the planned POST body without hitting
GitHub. Composes optional branch-create + PR-create.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection, NextAction
from stronghold.playbooks.github._client import GitHubClient

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "owner/repo"},
        "branch": {"type": "string", "description": "head branch (will be created if missing)"},
        "title": {"type": "string"},
        "body": {"type": "string", "default": ""},
        "base": {"type": "string", "default": "main"},
        "create_branch": {"type": "boolean", "default": False},
    },
    "required": ["repo", "branch", "title"],
}


@playbook(
    "open_pull_request",
    description="Open a GitHub PR. Supports dry_run and optional branch creation.",
    input_schema=_INPUT_SCHEMA,
    writes=True,
    next_actions_hint=("review_pull_request", "respond_to_issue"),
)
async def open_pull_request(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    repo = inputs["repo"]
    branch = inputs["branch"]
    title = inputs["title"]
    body = inputs.get("body", "")
    base = inputs.get("base", "main")
    create_branch = bool(inputs.get("create_branch", False))
    dry_run = bool(inputs.get("dry_run", False))

    if "/" not in repo:
        raise ValueError(f"repo must be 'owner/repo', got {repo!r}")
    owner, name = repo.split("/", 1)

    plan_lines = [
        f"- repo: `{owner}/{name}`",
        f"- head: `{branch}`",
        f"- base: `{base}`",
        f"- title: {title}",
    ]
    if create_branch:
        plan_lines.append(f"- will create branch `{branch}` from `{base}` first")
    if body:
        plan_lines.append(f"- body: {len(body)} chars")

    if dry_run:
        return Brief(
            title=f"Dry-run: open PR in {owner}/{name}",
            summary=f"would open PR '{title}' head={branch} base={base}",
            sections=(BriefSection(heading="Plan", body="\n".join(plan_lines)),),
            next_actions=(
                NextAction(
                    tool="open_pull_request",
                    args={
                        "repo": repo,
                        "branch": branch,
                        "title": title,
                        "body": body,
                        "base": base,
                    },
                    reason="execute the plan (dry_run=False)",
                ),
            ),
            source_calls=("(dry-run — no upstream calls)",),
        )

    client = GitHubClient()
    calls: list[str] = []
    if create_branch:
        ref = await client.get_json(f"/repos/{owner}/{name}/git/ref/heads/{base}")
        sha = ref["object"]["sha"]
        resp = await client.request(
            "POST",
            f"/repos/{owner}/{name}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        resp.raise_for_status()
        calls.append(f"POST /repos/{owner}/{name}/git/refs")

    resp = await client.request(
        "POST",
        f"/repos/{owner}/{name}/pulls",
        json_body={"title": title, "body": body, "head": branch, "base": base},
    )
    resp.raise_for_status()
    pr = resp.json()
    calls.append(f"POST /repos/{owner}/{name}/pulls")

    return Brief(
        title=f"Opened PR #{pr['number']} in {owner}/{name}",
        summary=f"{pr['html_url']} — state={pr['state']}",
        sections=(
            BriefSection(
                heading="Details",
                body=f"- head `{branch}` → base `{base}`\n- title: {title}",
            ),
        ),
        next_actions=(
            NextAction(
                tool="review_pull_request",
                args={"url": pr["html_url"]},
                reason="preview the PR you just opened",
            ),
        ),
        source_calls=tuple(calls),
    )


class OpenPullRequestPlaybook:
    @property
    def definition(self) -> Any:
        return open_pull_request._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await open_pull_request(inputs, ctx)
