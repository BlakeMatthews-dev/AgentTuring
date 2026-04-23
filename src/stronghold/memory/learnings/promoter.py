"""Auto-promotion logic for learnings.

When a learning's hit_count crosses the promotion threshold,
it graduates to 'promoted' status and optionally triggers
skill mutation via the SkillForge protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.memory.learnings.approval import LearningApprovalGate
    from stronghold.memory.mutations import InMemorySkillMutationStore
    from stronghold.protocols.memory import LearningStore
    from stronghold.protocols.skills import SkillForge
    from stronghold.types.memory import Learning

logger = logging.getLogger("stronghold.promoter")


class LearningPromoter:
    """Checks and executes promotions with an optional approval gate.

    If an approval_gate is configured, learnings enter 'pending_approval'
    instead of auto-promoting. An admin must approve before mutation fires.
    """

    def __init__(
        self,
        learning_store: LearningStore,
        *,
        threshold: int = 5,
        skill_forge: SkillForge | None = None,
        mutation_store: InMemorySkillMutationStore | None = None,
        approval_gate: LearningApprovalGate | None = None,
    ) -> None:
        self._store = learning_store
        self._threshold = threshold
        self._forge = skill_forge
        self._mutation_store = mutation_store
        self._approval_gate = approval_gate

    async def check_and_promote(self, org_id: str = "") -> list[Learning]:
        """Check for learnings that should be promoted.

        With approval gate: creates approval requests (pending state).
        Without approval gate: auto-promotes immediately (legacy behavior).

        Returns the list of newly promoted learnings.
        """
        if self._approval_gate:
            return await self._check_with_gate(org_id)
        return await self._check_auto(org_id)

    async def _check_auto(self, org_id: str = "") -> list[Learning]:
        """Legacy auto-promotion (no gate)."""
        promoted = await self._store.check_auto_promotions(self._threshold, org_id=org_id)
        for learning in promoted:
            logger.info(
                "Auto-promoted learning #%s (hits=%d): %s",
                learning.id,
                learning.hit_count,
                learning.learning[:80],
            )
            if learning.tool_name and self._forge:
                await self._try_mutate_skill(learning)
        return promoted

    async def _check_with_gate(self, org_id: str = "") -> list[Learning]:
        """Gate-aware promotion: queue for approval + process approved."""
        assert self._approval_gate is not None  # nosec B101 - mypy narrowing; check_and_promote only calls this branch when the gate is set
        promoted: list[Learning] = []

        # 1. Queue high-hit learnings for approval
        candidates = await self._store.find_relevant(
            "",
            org_id=org_id,
            max_results=100,
        )
        for lr in candidates:
            if lr.hit_count >= self._threshold and lr.status == "active":
                self._approval_gate.request_approval(
                    learning_id=lr.id or 0,
                    org_id=lr.org_id,
                    learning_preview=lr.learning[:200],
                    tool_name=lr.tool_name,
                    hit_count=lr.hit_count,
                )

        # 2. Process approved learnings
        approved_ids = self._approval_gate.get_approved_ids()
        for lid in approved_ids:
            # Find the learning and promote it
            for lr in candidates:
                if lr.id == lid and lr.status == "active":
                    logger.info(
                        "Gate-approved promotion: learning #%d (hits=%d)",
                        lid,
                        lr.hit_count,
                    )
                    if lr.tool_name and self._forge:
                        await self._try_mutate_skill(lr)
                    self._approval_gate.mark_promoted(lid)
                    promoted.append(lr)

        return promoted

    async def _try_mutate_skill(self, learning: Learning) -> None:
        """Attempt to mutate a skill based on a promoted learning."""
        if not self._forge:
            return

        try:
            result = await self._forge.mutate(learning.tool_name, learning)
            if result.get("status") == "mutated" and self._mutation_store:
                from stronghold.types.memory import SkillMutation

                mutation = SkillMutation(
                    skill_name=learning.tool_name,
                    learning_id=learning.id or 0,
                    old_prompt_hash=result.get("old_hash", ""),
                    new_prompt_hash=result.get("new_hash", ""),
                )
                await self._mutation_store.record(mutation)
                logger.info(
                    "Skill mutated: %s from learning #%s (%s -> %s)",
                    learning.tool_name,
                    learning.id,
                    result.get("old_hash", ""),
                    result.get("new_hash", ""),
                )
            elif result.get("status") == "error":
                logger.warning(
                    "Skill mutation failed for %s: %s",
                    learning.tool_name,
                    result.get("error"),
                )
        except Exception as e:
            logger.warning("Skill mutation exception for %s: %s", learning.tool_name, e)
