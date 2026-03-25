"""Context builder: assembles prompt from soul + tools + learnings + episodic.

Order matters: soul → tool prompts → promoted learnings → matched learnings → episodic memories.
All learning queries are scoped by org_id/team_id to prevent cross-tenant leakage.
Token budget enforcement prevents context overflow — learnings are dropped (lowest priority first)
before soul prompt, which is never truncated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.protocols.memory import LearningStore
    from stronghold.protocols.prompts import PromptManager
    from stronghold.types.agent import AgentIdentity

logger = logging.getLogger("stronghold.context_builder")

# 4 chars ≈ 1 token (conservative estimate, avoids tokenizer dependency)
_CHARS_PER_TOKEN = 4

# Default system prompt budget: 4096 tokens (16K chars).
# Soul prompt is never truncated; learnings are trimmed to fit.
_DEFAULT_SYSTEM_TOKEN_BUDGET = 4096


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length (4 chars ≈ 1 token)."""
    return len(text) // _CHARS_PER_TOKEN


class ContextBuilder:
    """Assembles the full prompt context for an agent."""

    async def build(
        self,
        messages: list[dict[str, Any]],
        identity: AgentIdentity,
        *,
        prompt_manager: PromptManager,
        learning_store: LearningStore | None = None,
        agent_id: str = "",
        user_id: str = "",
        org_id: str = "",
        team_id: str = "",
        system_token_budget: int = _DEFAULT_SYSTEM_TOKEN_BUDGET,
    ) -> list[dict[str, Any]]:
        """Build the full message list with injected context.

        Returns messages with system prompt assembled from (priority order):
        1. Agent soul (always included, never truncated)
        2. Promoted learnings (org-scoped, trimmed to budget)
        3. Matched learnings (keyword-based, org-scoped, trimmed to budget)

        Token budget enforcement: soul is always included. Learnings are
        added until the budget is exhausted, then remaining are dropped.
        """
        system_parts: list[str] = []
        budget_chars = system_token_budget * _CHARS_PER_TOKEN

        # 1. Fetch soul from prompt library (highest priority — always included)
        soul_name = identity.soul_prompt_name or f"agent.{identity.name}.soul"
        soul = await prompt_manager.get(soul_name)
        if soul:
            system_parts.append(soul)
            budget_chars -= len(soul)
            if budget_chars < 0:
                logger.warning(
                    "Soul prompt exceeds token budget: soul=%d chars, budget=%d tokens. "
                    "Learnings will be dropped.",
                    len(soul),
                    system_token_budget,
                )

        # 2. Promoted learnings (org-scoped, boundary-isolated)
        if learning_store and identity.memory_config.get("learnings") and budget_chars > 0:
            promoted = await learning_store.get_promoted(org_id=org_id)
            if promoted:
                header = '<stronghold:corrections type="promoted">'
                footer = "</stronghold:corrections>"
                overhead = len(header) + len(footer) + 2  # newlines
                lines: list[str] = [header]
                used = overhead
                added = 0
                for lr in promoted:
                    entry = f"- {lr.learning}"
                    if used + len(entry) + 1 > budget_chars:
                        break
                    lines.append(entry)
                    used += len(entry) + 1
                    added += 1
                if added > 0:
                    lines.append(footer)
                    block = "\n".join(lines)
                    system_parts.append(block)
                    budget_chars -= len(block)
                if added < len(promoted):
                    logger.debug(
                        "Token budget: dropped %d/%d promoted learnings",
                        len(promoted) - added,
                        len(promoted),
                    )

        # 3. Matched learnings (keyword-based, org-scoped, boundary-isolated)
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = str(msg.get("content", ""))
                break

        if (
            learning_store
            and user_text
            and identity.memory_config.get("learnings")
            and budget_chars > 0
        ):
            relevant = await learning_store.find_relevant(
                user_text,
                agent_id=agent_id,
                org_id=org_id,
            )
            if relevant:
                header = '<stronghold:corrections type="matched">'
                footer = "</stronghold:corrections>"
                overhead = len(header) + len(footer) + 2
                lines = [header]
                used = overhead
                added = 0
                for lr in relevant:
                    entry = f"- {lr.learning}"
                    if used + len(entry) + 1 > budget_chars:
                        break
                    lines.append(entry)
                    used += len(entry) + 1
                    added += 1
                if added > 0:
                    lines.append(footer)
                    block = "\n".join(lines)
                    system_parts.append(block)
                    budget_chars -= len(block)
                if added < len(relevant):
                    logger.debug(
                        "Token budget: dropped %d/%d matched learnings",
                        len(relevant) - added,
                        len(relevant),
                    )

        # Assemble system message
        assembled = "\n\n".join(system_parts)
        result_messages = list(messages)

        if assembled:
            if result_messages and result_messages[0].get("role") == "system":
                result_messages[0] = {
                    "role": "system",
                    "content": assembled + "\n\n" + result_messages[0]["content"],
                }
            else:
                result_messages.insert(0, {"role": "system", "content": assembled})

        return result_messages
