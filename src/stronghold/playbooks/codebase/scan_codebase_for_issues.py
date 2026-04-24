"""scan_codebase_for_issues playbook — compose scanner detectors into one Brief.

Wraps `stronghold.tools.scanner.scan_for_good_first_issues` (which runs
four detectors: missing fakes, missing docstrings, untested modules,
TODO/FIXME comments, sidebar inconsistencies) and renders the output as
a ranked candidate-issue brief. The agent can then hand individual
suggestions to `respond_to_issue` or `open_pull_request`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection, NextAction
from stronghold.tools.scanner import scan_for_good_first_issues

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project_root": {
            "type": "string",
            "description": "Absolute path to the project root (defaults to CWD).",
        },
        "limit": {
            "type": "integer",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
            "description": "Max suggestions to render.",
        },
        "categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional category filter (e.g. ['missing-fakes']).",
        },
    },
    "required": [],
}


@playbook(
    "scan_codebase_for_issues",
    description=(
        "Scan the Stronghold source tree for candidate good-first-issues: "
        "missing fakes, missing docstrings, untested modules, TODO/FIXME, "
        "sidebar inconsistencies. Composes 4 detectors into one Brief."
    ),
    input_schema=_INPUT_SCHEMA,
    next_actions_hint=("respond_to_issue",),
)
async def scan_codebase_for_issues(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    root_str = inputs.get("project_root") or str(Path.cwd())
    root = Path(root_str).resolve()
    if not root.is_dir():
        return Brief(
            title="scan_codebase_for_issues: invalid root",
            summary=f"not a directory: {root}",
            flags=("bad-input",),
        )
    limit = int(inputs.get("limit", 10))
    categories = tuple(str(c) for c in (inputs.get("categories") or ()))

    suggestions = scan_for_good_first_issues(root)
    if categories:
        suggestions = [s for s in suggestions if s.category in categories]
    suggestions = suggestions[:limit]

    if not suggestions:
        return Brief(
            title=f"No candidate issues in {root.name}",
            summary=f"scanned {root} — 0 matches"
            + (f" (filtered to {categories})" if categories else ""),
            source_calls=("scanner: scan_for_good_first_issues",),
        )

    by_category: dict[str, list[Any]] = {}
    for s in suggestions:
        by_category.setdefault(s.category, []).append(s)

    sections: list[BriefSection] = []
    for category, items in sorted(by_category.items()):
        body_lines: list[str] = []
        for s in items:
            body_lines.append(f"### {s.title}")
            body_lines.append(f"_{s.estimated_scope}_ — {s.description}")
            if s.files:
                body_lines.append("Files:")
                for f in s.files[:3]:
                    body_lines.append(f"- `{f}`")
                if len(s.files) > 3:
                    body_lines.append(f"- …and {len(s.files) - 3} more")
            body_lines.append("")
        sections.append(BriefSection(heading=category, body="\n".join(body_lines)))

    next_actions = tuple(
        NextAction(
            tool="respond_to_issue",
            args={"url": "", "action": "comment", "message": s.title, "dry_run": True},
            reason=f"draft a ticket from: {s.title[:60]}",
        )
        for s in suggestions[:3]
    )
    return Brief(
        title=f"{len(suggestions)} candidate issue(s) in {root.name}",
        summary=(
            f"scanned {root} — {len(suggestions)} suggestion(s) "
            f"across {len(by_category)} categor(y/ies)"
        ),
        sections=tuple(sections),
        next_actions=next_actions,
        source_calls=("scanner: scan_for_good_first_issues",),
    )


class ScanCodebaseForIssuesPlaybook:
    @property
    def definition(self) -> Any:
        return scan_codebase_for_issues._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await scan_codebase_for_issues(inputs, ctx)
