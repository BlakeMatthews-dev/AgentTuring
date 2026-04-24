"""Brief: structured-markdown output for agent-oriented playbooks.

A Brief is what every playbook returns. It renders to markdown that flows
into ToolResult.content, shaped for reasoning LLMs (not programmers):
title + short summary + sections + warning flags + next-action hints.

Hard rendering budget keeps tool output small enough to fit in context
without truncation by react.py's 16 KB safety net.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_BYTES = 6144
LARGE_MAX_BYTES = 12288
SUMMARY_SOFT_LIMIT = 400


@dataclass(frozen=True)
class BriefSection:
    """A named section within a Brief. Body is markdown, already Warden-scanned."""

    heading: str
    body: str


@dataclass(frozen=True)
class NextAction:
    """Suggested follow-up tool call the reasoner probably wants next.

    `args` is a JSON-serializable dict of suggested values — not a partial
    tool call. The reasoner must pass it through the standard tool-call
    path so Sentinel schema-validates it.
    """

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class Brief:
    """Agent-oriented result of a playbook execution."""

    title: str
    summary: str = ""
    sections: tuple[BriefSection, ...] = ()
    flags: tuple[str, ...] = ()
    next_actions: tuple[NextAction, ...] = ()
    source_calls: tuple[str, ...] = ()

    def to_markdown(self, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        """Render as markdown, truncating from the bottom if over budget."""
        parts: list[str] = [f"# {self.title}", ""]

        if self.summary:
            summary = self.summary
            if len(summary) > SUMMARY_SOFT_LIMIT:
                summary = summary[: SUMMARY_SOFT_LIMIT - 1] + "…"
            parts.extend([summary, ""])

        if self.flags:
            parts.extend([f"> Flags: {', '.join(self.flags)}", ""])

        for section in self.sections:
            parts.extend([f"## {section.heading}", "", section.body, ""])

        if self.next_actions:
            parts.extend(["## What's next", ""])
            for action in self.next_actions:
                args_repr = json.dumps(action.args, separators=(", ", ": "))
                line = f"- `{action.tool}({args_repr})`"
                if action.reason:
                    line += f" — {action.reason}"
                parts.append(line)
            parts.append("")

        rendered = "\n".join(parts).rstrip() + "\n"
        if len(rendered.encode("utf-8")) <= max_bytes:
            return rendered
        return _truncate_markdown(rendered, max_bytes)


def _truncate_markdown(rendered: str, max_bytes: int) -> str:
    """Truncate markdown at a line boundary, appending a notice."""
    notice = "\n\n> _Truncated: brief exceeded budget._\n"
    budget = max_bytes - len(notice.encode("utf-8"))
    encoded = rendered.encode("utf-8")
    if budget <= 0:
        return rendered[:max_bytes]
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    last_nl = truncated.rfind("\n")
    if last_nl > 0:
        truncated = truncated[:last_nl]
    return truncated + notice
