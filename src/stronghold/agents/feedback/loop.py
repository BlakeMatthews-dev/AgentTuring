"""FeedbackLoop — orchestrates the RLHF cycle.

Auditor reviews PR -> extract learnings -> store in agent memory -> track metrics.

This is the glue that connects the Auditor's output to Mason's input,
using the existing LearningStore infrastructure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.protocols.feedback import FeedbackExtractor, ViolationStore
    from stronghold.protocols.memory import LearningStore
    from stronghold.types.feedback import ReviewResult

logger = logging.getLogger("stronghold.feedback")


class FeedbackLoop:
    """Orchestrates the RLHF cycle between Auditor and Mason.

    Takes a ReviewResult (from Auditor), extracts Learning objects
    (via FeedbackExtractor), stores them in the authoring agent's
    memory (via LearningStore), and tracks metrics (via ViolationStore).
    """

    def __init__(
        self,
        extractor: FeedbackExtractor,
        learning_store: LearningStore,
        violation_store: ViolationStore,
    ) -> None:
        self._extractor = extractor
        self._learning_store = learning_store
        self._violation_store = violation_store

    async def process_review(self, result: ReviewResult) -> int:
        """Process a review result through the full RLHF cycle.

        Returns the number of learnings stored.
        """
        # 1. Track violations for metrics
        self._violation_store.record_review(result)

        # 2. Extract learnings from findings
        learnings = self._extractor.extract_learnings(result)

        # 3. Store each learning in the authoring agent's memory
        stored_count = 0
        for learning in learnings:
            learning_id = await self._learning_store.store(learning)
            if learning_id > 0:
                stored_count += 1
                logger.debug(
                    "Stored learning %d for agent %s: %s",
                    learning_id,
                    result.agent_id,
                    learning.learning[:80],
                )

        # 4. Log metrics
        metrics = self._violation_store.get_metrics(result.agent_id)
        logger.info(
            "RLHF cycle for PR #%d (agent=%s): %d findings, %d learnings stored, "
            "trend=%s, avg=%.1f findings/PR",
            result.pr_number,
            result.agent_id,
            len(result.findings),
            stored_count,
            metrics.trend,
            metrics.findings_per_pr,
        )

        return stored_count
