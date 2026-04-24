"""triage_issues playbook — NL-friendly issue search + brief summary."""

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
        "query": {
            "type": "string",
            "description": "GitHub search grammar or natural language (e.g. 'open P0 bugs').",
        },
        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
    },
    "required": ["repo", "query"],
}

_NL_LABEL_HINTS = {
    "p0": "label:P0",
    "bug": "label:bug",
    "bugs": "label:bug",
    "security": "label:security",
    "regression": "label:regression",
}


@playbook(
    "triage_issues",
    description="Search and summarize GitHub issues. Accepts NL or raw search grammar.",
    input_schema=_INPUT_SCHEMA,
    next_actions_hint=("respond_to_issue",),
)
async def triage_issues(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    repo = inputs["repo"]
    user_query = inputs["query"]
    limit = int(inputs.get("limit", 10))
    if "/" not in repo:
        raise ValueError(f"repo must be 'owner/repo', got {repo!r}")
    search_q = _translate_query(user_query, repo)

    client = GitHubClient()
    resp = await client.get_json(
        "/search/issues",
        params={"q": search_q, "per_page": limit, "sort": "updated", "order": "desc"},
    )
    items = resp.get("items", [])[:limit]
    if not items:
        return Brief(
            title=f"No matches in {repo}",
            summary=f"search `{search_q}` returned 0 results",
            source_calls=(f"GET /search/issues?q={search_q}",),
        )

    lines = [
        f"- [#{i['number']}]({i['html_url']}) {i['title']}"
        f" — {i['state']}"
        + (", ".join([f" `{lb['name']}`" for lb in i.get("labels", [])]) if i.get("labels") else "")
        for i in items
    ]
    return Brief(
        title=f"Triage: {len(items)} issue(s) in {repo}",
        summary=f"query `{search_q}` → {len(items)} results (limit {limit})",
        sections=(BriefSection(heading="Matches", body="\n".join(lines)),),
        next_actions=tuple(
            NextAction(
                tool="respond_to_issue",
                args={"url": i["html_url"], "action": "comment", "message": "", "dry_run": True},
                reason=f"respond to #{i['number']}",
            )
            for i in items[:3]
        ),
        source_calls=(f"GET /search/issues?q={search_q}",),
    )


def _translate_query(user_query: str, repo: str) -> str:
    """Minimal NL→search-grammar translation.

    Works for the common cases ("open P0 bugs"); the full helper in
    plan §2.3 will live in src/stronghold/playbooks/nl/ once more
    playbooks need it.
    """
    q = user_query.strip()
    if f"repo:{repo}" not in q:
        q = f"repo:{repo} {q}"
    lowered = q.lower()
    if " state:" not in lowered and "is:open" not in lowered and "is:closed" not in lowered:
        if "open" in lowered:
            q += " state:open"
        elif "closed" in lowered:
            q += " state:closed"
    parts = q.split()
    for i, token in enumerate(parts):
        mapped = _NL_LABEL_HINTS.get(token.lower())
        if mapped and mapped not in q:
            parts[i] = mapped
    if "type:issue" not in q and "is:pr" not in q:
        parts.append("type:issue")
    return " ".join(parts)


class TriageIssuesPlaybook:
    @property
    def definition(self) -> Any:
        return triage_issues._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await triage_issues(inputs, ctx)
