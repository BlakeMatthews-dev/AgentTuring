"""read_workspace playbook — tree overview + sampled file contents in one Brief."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.base import playbook
from stronghold.playbooks.brief import Brief, BriefSection
from stronghold.tools.file_ops import FileOpsExecutor

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workspace": {"type": "string", "description": "Workspace root directory."},
        "path": {"type": "string", "default": ".", "description": "Relative path to inspect."},
        "read_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of paths to read sampled content from.",
        },
    },
    "required": ["workspace"],
}

_MAX_SAMPLE_BYTES = 1500


@playbook(
    "read_workspace",
    description=(
        "Read a workspace directory tree; optionally sample specific file "
        "contents in one brief. Reuses FileOpsExecutor under the same sandbox."
    ),
    input_schema=_INPUT_SCHEMA,
)
async def read_workspace(inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
    workspace = inputs["workspace"]
    path = inputs.get("path", ".")
    files_to_read: list[str] = list(inputs.get("read_files") or [])

    file_ops = FileOpsExecutor()
    list_result = await file_ops.execute(
        {"action": "list", "workspace": workspace, "path": path},
    )
    if not list_result.success:
        return Brief(
            title=f"read_workspace failed at {path}",
            summary=str(list_result.error or "list failed"),
            flags=("fs-error",),
        )
    try:
        entries = json.loads(list_result.content)
    except json.JSONDecodeError:
        entries = {"raw": list_result.content}

    sections: list[BriefSection] = [
        BriefSection(
            heading=f"Tree: {path}",
            body=f"```json\n{json.dumps(entries, indent=2)[:1500]}\n```",
        ),
    ]
    calls = [f"file_ops: list {path}"]

    for f in files_to_read:
        read_result = await file_ops.execute(
            {"action": "read", "workspace": workspace, "path": f},
        )
        if read_result.success:
            content = read_result.content
            if len(content) > _MAX_SAMPLE_BYTES:
                content = content[:_MAX_SAMPLE_BYTES] + "\n... (truncated)"
            sections.append(
                BriefSection(heading=f"Contents: {f}", body=f"```\n{content}\n```"),
            )
        else:
            sections.append(
                BriefSection(
                    heading=f"Contents: {f}",
                    body=f"_error: {read_result.error}_",
                ),
            )
        calls.append(f"file_ops: read {f}")

    return Brief(
        title=f"Workspace read: {path}",
        summary=(f"listed 1 directory + {len(files_to_read)} sampled file(s) at {path}"),
        sections=tuple(sections),
        source_calls=tuple(calls),
    )


class ReadWorkspacePlaybook:
    @property
    def definition(self) -> Any:
        return read_workspace._playbook_definition  # type: ignore[attr-defined]

    async def execute(self, inputs: dict[str, Any], ctx: PlaybookContext) -> Brief:
        return await read_workspace(inputs, ctx)
