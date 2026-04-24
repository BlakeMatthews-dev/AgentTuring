"""Agent-oriented Playbook abstraction.

Playbooks are task-oriented tools whose executor composes multiple backend
operations server-side and returns a markdown Brief shaped for reasoning
LLMs. Peer abstraction to @tool-decorated tools in src/stronghold/tools/;
the two coexist via PlaybookToolExecutor (Phase B).

See docs/adr/ADR-K8S-020-mcp-server-gateway-orchestrator.md and the
'Agent-Oriented MCP Redesign' plan for context.
"""

from __future__ import annotations

from stronghold.playbooks.base import PlaybookDefinition, playbook
from stronghold.playbooks.brief import Brief, BriefSection, NextAction

__all__ = [
    "Brief",
    "BriefSection",
    "NextAction",
    "PlaybookDefinition",
    "playbook",
]
