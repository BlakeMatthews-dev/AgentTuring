"""list_repo_activity playbook — recent PRs + issues + commits in a repo."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.playbooks.github._client import GitHubClient

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_KINDS = ("prs", "issues", "commits", "all")

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "owner/repo"},
        "since": {"type": "string", "description": "ISO 8601 timestamp (optional)"},
        "kind": {"type": "string", "enum": list(_KINDS), "default": "all"},
        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
    },
    "required": ["repo"],
}


@playbook(
    "list_repo_activity",
    description="Summarize recent PRs, issues, and commits in a repo for the last N days.",
    input_schema=_INPUT_SCHEMA,
)
async def list_repo_activity(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    repo = inputs["repo"]
    since = inputs.get("since")
    kind = inputs.get("kind", "all")
    limit = int(inputs.get("limit", 10))
    if "/" not in repo:
        raise ValueError(f"repo must be 'owner/repo', got {repo!r}")
    owner, name = repo.split("/", 1)

    client = GitHubClient()
    prs_task: asyncio.Future[Any] | asyncio.Task[Any]
    issues_task: asyncio.Future[Any] | asyncio.Task[Any]
    commits_task: asyncio.Future[Any] | asyncio.Task[Any]

    async def _noop() -> list[Any]:
        return []

    prs_task = asyncio.create_task(
        client.get_json(
            f"/repos/{owner}/{name}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": limit},
        )
        if kind in ("prs", "all")
        else _noop()
    )
    issues_task = asyncio.create_task(
        client.get_json(
            f"/repos/{owner}/{name}/issues",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": limit}
            | ({"since": since} if since else {}),
        )
        if kind in ("issues", "all")
        else _noop()
    )
    commits_params: dict[str, Any] = {"per_page": limit}
    if since:
        commits_params["since"] = since
    commits_task = asyncio.create_task(
        client.get_json(f"/repos/{owner}/{name}/commits", params=commits_params)
        if kind in ("commits", "all")
        else _noop()
    )

    prs, issues, commits = await asyncio.gather(prs_task, issues_task, commits_task)

    # Filter PRs out of issues list (GitHub returns both)
    issues_only = [i for i in issues if "pull_request" not in i]

    sections = []
    if kind in ("prs", "all") and prs:
        sections.append(
            BriefSection(
                heading="Recent PRs",
                body="\n".join(
                    f"- [#{p['number']}]({p['html_url']}) {p['title']} — {p['state']}" for p in prs
                ),
            ),
        )
    if kind in ("issues", "all") and issues_only:
        sections.append(
            BriefSection(
                heading="Recent issues",
                body="\n".join(
                    f"- [#{i['number']}]({i['html_url']}) {i['title']} — {i['state']}"
                    for i in issues_only
                ),
            ),
        )
    if kind in ("commits", "all") and commits:
        sections.append(
            BriefSection(
                heading="Recent commits",
                body="\n".join(
                    f"- {c.get('sha', '')[:7]} — "
                    + (c.get("commit", {}).get("message", "") or "").splitlines()[0]
                    for c in commits
                ),
            ),
        )

    calls: list[str] = []
    if kind in ("prs", "all"):
        calls.append(f"GET /repos/{owner}/{name}/pulls")
    if kind in ("issues", "all"):
        calls.append(f"GET /repos/{owner}/{name}/issues")
    if kind in ("commits", "all"):
        calls.append(f"GET /repos/{owner}/{name}/commits")

    return Brief(
        title=f"Activity in {repo}",
        summary=(
            f"PRs={len(prs) if kind in ('prs', 'all') else 0}, "
            f"issues={len(issues_only) if kind in ('issues', 'all') else 0}, "
            f"commits={len(commits) if kind in ('commits', 'all') else 0}"
        ),
        sections=tuple(sections),
        source_calls=tuple(calls),
    )


class ListRepoActivityPlaybook:
    @property
    def definition(self) -> Any:
        return list_repo_activity._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await list_repo_activity(inputs, ctx)
