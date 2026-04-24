"""merge_pull_request playbook — merge a PR with dry_run preview of the plan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.playbooks.github._client import GitHubClient, parse_pr_url

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "method": {"type": "string", "enum": ["merge", "squash", "rebase"], "default": "squash"},
        "commit_title": {"type": "string"},
        "commit_message": {"type": "string"},
    },
    "required": ["url"],
}


@playbook(
    "merge_pull_request",
    description="Merge a GitHub PR. Dry-run shows the planned method and check status.",
    input_schema=_INPUT_SCHEMA,
    writes=True,
    dry_run_default=True,
    next_actions_hint=("review_pull_request",),
)
async def merge_pull_request(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    ref = parse_pr_url(inputs["url"])
    method = inputs.get("method", "squash")
    dry_run = bool(inputs.get("dry_run", True))

    client = GitHubClient()
    pr = await client.get_json(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
    head_sha = pr.get("head", {}).get("sha", "")
    status_payload: dict[str, Any] = {"state": "unknown", "statuses": []}
    if head_sha:
        status_payload = await client.get_json(
            f"/repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status",
        )

    flags: list[str] = []
    if pr.get("mergeable") is False or pr.get("mergeable_state") == "dirty":
        flags.append("merge conflicts")
    if status_payload.get("state") == "failure":
        flags.append("failing required checks")
    if pr.get("draft"):
        flags.append("draft PR — GitHub will reject merge")

    plan_body = "\n".join(
        [
            f"- PR #{ref.number} `{ref.owner}/{ref.repo}`",
            f"- method: **{method}**",
            f"- head sha: `{head_sha[:12]}`",
            f"- mergeable: {pr.get('mergeable_state', 'unknown')}",
            f"- overall check state: {status_payload.get('state', 'unknown')}",
        ]
    )

    if dry_run:
        return Brief(
            title=f"Dry-run: merge_pull_request #{ref.number}",
            summary=f"would {method}-merge PR #{ref.number} in {ref.owner}/{ref.repo}",
            sections=(BriefSection(heading="Merge plan", body=plan_body),),
            flags=tuple(flags),
            source_calls=(
                f"GET /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}",
                f"GET /repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status",
            ),
        )

    body_json: dict[str, Any] = {"merge_method": method}
    if inputs.get("commit_title"):
        body_json["commit_title"] = inputs["commit_title"]
    if inputs.get("commit_message"):
        body_json["commit_message"] = inputs["commit_message"]

    resp = await client.request(
        "PUT",
        f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/merge",
        json_body=body_json,
    )
    if resp.status_code >= 400:
        return Brief(
            title=f"Failed to merge PR #{ref.number}",
            summary=f"GitHub {resp.status_code}: {resp.text[:200]}",
            flags=(*flags, f"github-{resp.status_code}"),
            source_calls=(f"PUT /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/merge",),
        )
    merged = resp.json()
    return Brief(
        title=f"Merged PR #{ref.number}",
        summary=f"merged={merged.get('merged', False)} sha={merged.get('sha', '')[:12]}",
        sections=(BriefSection(heading="Result", body=plan_body),),
        flags=tuple(flags),
        source_calls=(f"PUT /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/merge",),
    )


class MergePullRequestPlaybook:
    @property
    def definition(self) -> Any:
        return merge_pull_request._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await merge_pull_request(inputs, ctx)
