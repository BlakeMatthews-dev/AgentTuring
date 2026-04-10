"""GitHub interaction helpers for the Builders pipeline.

Extracted from RuntimePipeline to enable isolated testing and reuse
across stage handlers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("stronghold.builders.pipeline")

# ── Pattern constants for prior-run detection ────────────────────────

# Matches both manual runs (run-<hex>) and scheduler runs (sched-<hex>).
# Backticks are optional — some comments use plain text form.
BUILDERS_RUN_PATTERN = re.compile(
    r"##\s*Builders Run\s*`?((?:run|sched)-[a-f0-9]+)`?"
)

# Matches Gatekeeper verdict comments posted to the parent issue.
# Case-insensitive; space before # is optional.
GATEKEEPER_VERDICT_PATTERN = re.compile(
    r"##\s*Gatekeeper Verdict on PR\s*#(\d+)",
    re.IGNORECASE,
)


def extract_files_from_issue_body(issue_body: str) -> list[str]:
    """Extract file paths from a Quartermaster-style '## Files' section.

    Returns the list of paths in document order, deduplicated.
    Returns [] if no '## Files' section is present.
    """
    match = re.search(
        r"^##\s+Files(?:\s+to\s+(?:create|modify|change))?\s*\n"
        r"((?:[ \t]*[-*][ \t]+\S.*\n?)+)",
        issue_body,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match:
        return []

    block = match.group(1)
    paths: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        entry = line.lstrip("-*").strip().strip("`").strip()
        entry = entry.split()[0] if entry else ""
        entry = entry.strip("`,;")
        if entry and entry not in paths:
            paths.append(entry)
    return paths


async def fetch_prior_runs(
    td: Any,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    exclude_run_id: str = "",
) -> list[dict[str, str]]:
    """Fetch prior Builders Run + Gatekeeper Verdict comments.

    Returns a list of dicts with `run_id` and `summary` for each prior
    signal Mason should learn from when re-running this issue.
    """
    result = await td.execute(
        "github",
        {
            "action": "list_issue_comments",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
        },
    )
    if result.startswith("Error:"):
        return []

    try:
        comments = json.loads(result)
    except Exception:
        return []
    if not isinstance(comments, list):
        return []

    prior_runs: list[dict[str, str]] = []

    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body", "") or ""

        run_match = BUILDERS_RUN_PATTERN.search(body)
        if run_match:
            run_id = run_match.group(1)
            if run_id == exclude_run_id:
                continue
            prior_runs.append({"run_id": run_id, "summary": body})
            continue

        gk_match = GATEKEEPER_VERDICT_PATTERN.search(body)
        if gk_match:
            pr_number = gk_match.group(1)
            comment_id = comment.get("id", "x")
            prior_runs.append(
                {
                    "run_id": f"gatekeeper-pr{pr_number}-{comment_id}",
                    "summary": body,
                }
            )

    return prior_runs


async def post_to_issue(
    td: Any,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
    *,
    run: Any = None,
) -> str:
    """Post or update the single run comment on the issue.

    First call creates the comment and stashes the ID on the run.
    Subsequent calls edit the same comment, appending new content.
    """
    comment_id = getattr(run, "_comment_id", None) if run else None

    if comment_id:
        old_body = getattr(run, "_comment_body", "")
        new_body = old_body + "\n\n---\n\n" + body
        if len(new_body) > 60000:
            new_body = new_body[-60000:]
        result = await td.execute(
            "github",
            {
                "action": "edit_comment",
                "owner": owner,
                "repo": repo,
                "comment_id": comment_id,
                "body": new_body,
            },
        )
        if run:
            run._comment_body = new_body
        return result

    run_id = getattr(run, "run_id", "?") if run else "?"
    header = f"## Builders Run `{run_id}`\n\n"
    full_body = header + body
    result = await td.execute(
        "github",
        {
            "action": "post_pr_comment",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": full_body,
        },
    )
    if run and not result.startswith("Error:"):
        try:
            data = json.loads(result)
            run._comment_id = data.get("id")
            run._comment_body = full_body
        except Exception:
            pass
    return result
