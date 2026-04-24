"""PlaybookToolExecutor: adapter exposing a Playbook as a ToolExecutor.

The adapter lets a playbook be invoked through the same callback surface
existing tool executors use (agents/strategies/react.py:165):

    tool_result = await tool_executor(tool_name, tool_args)

Inputs flow in as dict[str, Any]; the adapter calls PlaybookExecutor.execute,
renders the resulting Brief to markdown, and wraps it in ToolResult.content
so the agent loop does not need to know a playbook ran.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.brief import DEFAULT_MAX_BYTES, LARGE_MAX_BYTES, Brief
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.tool import ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.playbooks.base import PlaybookDefinition
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.playbooks import PlaybookExecutor
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.types.auth import AuthContext


logger = logging.getLogger("stronghold.playbooks.executor_adapter")


@dataclass
class PlaybookAdapterDeps:
    """Dependencies the adapter injects into every PlaybookContext.

    Kept as a dataclass so the container wires one instance and all adapters
    share the same LLM / Warden / tracer.
    """

    llm: LLMClient | None = None
    warden: Any | None = None
    tracer: TracingBackend | None = None
    allow_large_briefs: bool = False


class PlaybookToolExecutor:
    """ToolExecutor adapter wrapping a single PlaybookExecutor."""

    def __init__(
        self,
        playbook: PlaybookExecutor,
        deps: PlaybookAdapterDeps,
        *,
        auth_factory: Callable[[], AuthContext] | None = None,
    ) -> None:
        self._playbook = playbook
        self._deps = deps
        self._auth_factory = auth_factory or (lambda: SYSTEM_AUTH)

    @property
    def name(self) -> str:
        return self._playbook.definition.name

    @property
    def definition(self) -> PlaybookDefinition:
        return self._playbook.definition

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ctx = PlaybookContext(
            auth=self._auth_factory(),
            llm=self._deps.llm,
            warden=self._deps.warden,
            tracer=self._deps.tracer,
        )
        try:
            brief = await self._playbook.execute(arguments, ctx)
        except Exception as exc:  # noqa: BLE001 — tool boundary
            logger.warning("Playbook %s failed: %s", self.name, exc)
            return ToolResult(
                content="",
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not isinstance(brief, Brief):
            return ToolResult(
                content="",
                success=False,
                error=f"Playbook {self.name} returned {type(brief).__name__}, expected Brief",
            )

        max_bytes = LARGE_MAX_BYTES if self._deps.allow_large_briefs else DEFAULT_MAX_BYTES
        return ToolResult(
            content=brief.to_markdown(max_bytes=max_bytes),
            success=True,
            warden_flags=brief.flags,
        )
