"""review_pull_request playbook — the flagship agent-oriented PR review.

Composes six GitHub API calls concurrently:
- GET /repos/{o}/{r}/pulls/{n}          (metadata)
- GET /repos/{o}/{r}/pulls/{n}/files    (diff summary)
- GET /repos/{o}/{r}/pulls/{n}/commits  (commit list)
- GET /repos/{o}/{r}/pulls/{n}/reviews  (review activity)
- GET /repos/{o}/{r}/issues/{n}/comments (issue comments, PRs share numbering)
- GET /repos/{o}/{r}/commits/{head_sha}/status (check status)

…and emits a single Brief shaped for a reasoner: headline summary,
diff highlights, checks, review activity, flags for merge conflicts or
failing required checks, plus next-action hints (merge_pull_request dry
run, respond_to_issue).

Every section body is Warden-scanned before inclusion — PR descriptions
and comments are the classic prompt-injection surface.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection, NextAction
from stronghold.playbooks.github._client import GitHubClient, parse_pr_url

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

logger = logging.getLogger("stronghold.playbooks.github.review_pr")

_MAX_FILES_LISTED = 10
_MAX_DIFF_SAMPLE_LINES = 20
_INJECTION_HINTS = (
    "ignore previous",
    "ignore all previous",
    "disregard prior",
    "you are now",
    "system:",
    "<|im_start|>",
)


_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "GitHub PR URL (https://github.com/{owner}/{repo}/pull/{n}).",
        },
        "focus": {
            "type": "string",
            "enum": ["general", "security", "performance", "correctness"],
            "description": "Optional reviewer lens to emphasise in flags and hints.",
            "default": "general",
        },
    },
    "required": ["url"],
}


@playbook(
    "review_pull_request",
    description=(
        "Compose a markdown brief for a GitHub PR: metadata, diff highlights, "
        "check status, review activity, and next-action hints. Takes one GitHub "
        "PR URL plus optional review focus."
    ),
    input_schema=_INPUT_SCHEMA,
    next_actions_hint=("merge_pull_request", "respond_to_issue"),
)
async def review_pull_request(inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
    url = inputs.get("url", "")
    focus = inputs.get("focus", "general")
    ref = parse_pr_url(url)

    client = GitHubClient()
    pr, files, commits, reviews, comments = await asyncio.gather(
        client.get_json(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"),
        client.get_json(
            f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files",
            params={"per_page": 100},
        ),
        client.get_json(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/commits"),
        client.get_json(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/reviews"),
        client.get_json(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments"),
    )

    head_sha = pr.get("head", {}).get("sha", "")
    if head_sha:
        status = await client.get_json(f"/repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status")
    else:
        status = {"state": "unknown", "statuses": []}

    sections, flags, next_actions = _compose_brief(
        pr=pr,
        files=files,
        commits=commits,
        reviews=reviews,
        comments=comments,
        status=status,
        ref=ref,
        focus=focus,
    )

    # Warden-scan every section body — PR descriptions and comments are
    # the prompt-injection surface. We surface any flags the scanner
    # raises inline AND on Brief.flags so the adapter can set warden_flags.
    warden = getattr(ctx, "warden", None)
    if warden is not None:
        scanned_sections: list[BriefSection] = []
        for section in sections:
            verdict = await _safe_scan(warden, section.body)
            if verdict:
                flags = (*flags, f"suspicious content in {section.heading}: {verdict}")
            scanned_sections.append(section)
        sections = tuple(scanned_sections)

    title = f"PR #{ref.number} in {ref.owner}/{ref.repo}: {pr.get('title', '(untitled)')}"
    summary = _summarize(pr, files, status, reviews)
    return Brief(
        title=title,
        summary=summary,
        sections=sections,
        flags=flags,
        next_actions=next_actions,
        source_calls=(
            f"GET /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}",
            f"GET /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files",
            f"GET /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/commits",
            f"GET /repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/reviews",
            f"GET /repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments",
            f"GET /repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status",
        ),
    )


def _compose_brief(
    *,
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    status: dict[str, Any],
    ref: Any,
    focus: str,
) -> tuple[tuple[BriefSection, ...], tuple[str, ...], tuple[NextAction, ...]]:
    flags: list[str] = []
    if pr.get("mergeable") is False or pr.get("mergeable_state") == "dirty":
        flags.append("merge conflicts")
    if status.get("state") == "failure":
        flags.append("failing required checks")
    if pr.get("draft"):
        flags.append("draft PR")
    _scan_injection(pr.get("body", "") or "", flags, "PR description")
    for c in comments:
        _scan_injection(c.get("body", "") or "", flags, f"comment by @{_login(c)}")

    sections: list[BriefSection] = []
    sections.append(BriefSection(heading="Diff highlights", body=_render_diff(files)))
    sections.append(BriefSection(heading="Checks", body=_render_checks(status)))
    sections.append(BriefSection(heading="Review activity", body=_render_reviews(reviews)))
    if comments:
        sections.append(BriefSection(heading="Discussion", body=_render_comments(comments)))
    if len(commits) > 1:
        sections.append(BriefSection(heading="Recent commits", body=_render_commits(commits)))

    pr_url = pr.get("html_url", "")
    next_actions: list[NextAction] = []
    if status.get("state") == "success" and not pr.get("draft"):
        next_actions.append(
            NextAction(
                tool="merge_pull_request",
                args={"url": pr_url, "method": "squash", "dry_run": True},
                reason="preview the squash-merge plan",
            )
        )
    next_actions.append(
        NextAction(
            tool="respond_to_issue",
            args={"url": pr_url, "action": "comment", "message": "", "dry_run": True},
            reason=f"leave a {focus}-focused review comment",
        )
    )
    return tuple(sections), tuple(flags), tuple(next_actions)


def _summarize(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    status: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> str:
    author = _login(pr.get("user"))
    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)
    check_state = status.get("state", "unknown")
    approvals = sum(1 for r in reviews if r.get("state") == "APPROVED")
    changes_req = sum(1 for r in reviews if r.get("state") == "CHANGES_REQUESTED")
    parts = [
        f"author @{author}",
        f"+{additions}/-{deletions} across {len(files)} files",
        f"checks {check_state}",
        f"{approvals} approvals, {changes_req} requesting changes",
    ]
    return ", ".join(parts)


def _render_diff(files: list[dict[str, Any]]) -> str:
    if not files:
        return "_(no files changed)_"
    top = sorted(files, key=lambda f: int(f.get("changes", 0)), reverse=True)[:_MAX_FILES_LISTED]
    lines: list[str] = []
    for f in top:
        lines.append(
            f"- `{f.get('filename', '?')}` — +{f.get('additions', 0)}/-{f.get('deletions', 0)} "
            f"({f.get('status', 'modified')})"
        )
        patch = (f.get("patch") or "").splitlines()
        if patch:
            sample = "\n".join(patch[:_MAX_DIFF_SAMPLE_LINES])
            lines.append(f"  ```diff\n  {sample}\n  ```")
    omitted = max(0, len(files) - len(top))
    if omitted:
        lines.append(f"- _…{omitted} more files not shown_")
    return "\n".join(lines)


def _render_checks(status: dict[str, Any]) -> str:
    state = status.get("state", "unknown")
    statuses = status.get("statuses", []) or []
    if not statuses:
        return f"Overall: **{state}** (no individual checks reported)."
    lines = [f"Overall: **{state}**.", ""]
    for s in statuses:
        lines.append(
            f"- {s.get('context', '?')}: **{s.get('state', '?')}** — {s.get('description', '')}"
        )
    return "\n".join(lines)


def _render_reviews(reviews: list[dict[str, Any]]) -> str:
    if not reviews:
        return "_(no reviews yet)_"
    lines = []
    for r in reviews[-10:]:
        lines.append(f"- @{_login(r.get('user'))}: **{r.get('state', '?')}**")
    return "\n".join(lines)


def _render_comments(comments: list[dict[str, Any]]) -> str:
    lines = []
    for c in comments[-5:]:
        body = (c.get("body") or "").strip()
        snippet = body[:160] + ("…" if len(body) > 160 else "")
        lines.append(f"- @{_login(c.get('user'))}: {snippet}")
    return "\n".join(lines)


def _render_commits(commits: list[dict[str, Any]]) -> str:
    lines = []
    for c in commits[-10:]:
        msg = (c.get("commit", {}).get("message", "") or "").splitlines()[0]
        sha = (c.get("sha") or "")[:7]
        lines.append(f"- {sha} — {msg}")
    return "\n".join(lines)


def _login(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("login", "?"))
    return "?"


def _scan_injection(text: str, flags: list[str], where: str) -> None:
    lowered = text.lower()
    for hint in _INJECTION_HINTS:
        if hint in lowered:
            flags.append(f"possible prompt injection in {where}")
            return


async def _safe_scan(warden: Any, text: str) -> str:
    """Run warden.scan; return a descriptive string if flagged, empty if clean."""
    if not text or not hasattr(warden, "scan"):
        return ""
    try:
        verdict = await warden.scan(text, "tool_result")
    except Exception:  # noqa: BLE001
        return ""
    if getattr(verdict, "threat_level", "") in ("high", "critical"):
        return str(getattr(verdict, "threat_level", "flagged"))
    return ""


class ReviewPullRequestPlaybook:
    """PlaybookExecutor shim around the @playbook-decorated function.

    Registered into the playbook registry so the MCP wire server
    surfaces it as a tool.
    """

    @property
    def definition(self) -> Any:
        return review_pull_request._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await review_pull_request(inputs, ctx)
