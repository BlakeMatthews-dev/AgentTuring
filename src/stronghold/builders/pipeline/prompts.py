"""PromptLibrary: prompt fetching, composition, rendering.

Extracted from RuntimePipeline to enable isolated testing of prompt assembly.
"""

from __future__ import annotations

from typing import Any


class PromptLibrary:
    """Prompt management: fetch from prompt manager with fallback to defaults."""

    def __init__(self, prompt_manager: Any = None) -> None:
        self._pm = prompt_manager

    async def get(self, name: str) -> str:
        """Get a prompt by name. Falls back to BUILDER_PROMPT_DEFAULTS."""
        if self._pm:
            try:
                content = await self._pm.get(name)
                if content:
                    return content
            except Exception:
                pass
        from stronghold.builders.prompts import BUILDER_PROMPT_DEFAULTS

        return BUILDER_PROMPT_DEFAULTS.get(name, "")

    async def compose(self, *fragment_names: str) -> str:
        """Compose a prompt from named fragments in the prompt library."""
        parts = []
        for name in fragment_names:
            content = await self.get(name)
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def render(template: str, **kwargs: str) -> str:
        """Replace {{variable}} placeholders in a prompt template."""
        result = template
        for key, value in kwargs.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result

    async def seed_defaults(self) -> None:
        """Seed default builder prompts into the prompt library."""
        if not self._pm:
            return
        from stronghold.builders.prompts import BUILDER_PROMPT_DEFAULTS

        for name, content in BUILDER_PROMPT_DEFAULTS.items():
            try:
                await self._pm.upsert(name, content, label="production")
            except Exception:
                pass
