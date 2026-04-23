"""IntentClassifier logging module.

Logs classification decisions (intent, complexity, confidence),
agent selection, and stores in audit trail for debugging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("stronghold.classifier.logging")


@dataclass
class ClassificationDecision:
    """Classification decision log entry."""

    timestamp: datetime
    input_text: str
    intent_hint: str | None
    classified_intent: str
    confidence: float
    complexity: str
    selected_agent: str
    reason: str = ""
    metadata: dict[str, Any] | None = None


class ClassifierLogger:
    """Logger for IntentClassifier decisions."""

    def __init__(self) -> None:
        """Initialize ClassifierLogger."""
        self._decisions: list[ClassificationDecision] = []
        self._audit_enabled = True

    def log_decision(
        self,
        input_text: str,
        intent_hint: str | None,
        classified_intent: str,
        confidence: float,
        complexity: str,
        selected_agent: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a classification decision.

        Args:
            input_text: Input text to classify
            intent_hint: Intent hint from request
            classified_intent: Classified intent
            confidence: Confidence score (0-1)
            complexity: Complexity level (simple, medium, complex)
            selected_agent: Agent selected
            reason: Reason for selection
            metadata: Additional metadata
        """
        if not self._audit_enabled:
            return

        decision = ClassificationDecision(
            timestamp=datetime.now(UTC),
            input_text=input_text,
            intent_hint=intent_hint,
            classified_intent=classified_intent,
            confidence=confidence,
            complexity=complexity,
            selected_agent=selected_agent,
            reason=reason,
            metadata=metadata,
        )
        self._decisions.append(decision)
        logger.info(
            "Classification: intent=%s confidence=%.2f complexity=%s agent=%s reason=%s",
            classified_intent,
            confidence,
            complexity,
            selected_agent,
            reason,
        )

    def get_decisions(
        self,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[ClassificationDecision]:
        """Get recent classification decisions.

        Args:
            limit: Maximum number of decisions to return
            since: Only return decisions after this timestamp

        Returns:
            List of classification decisions
        """
        filtered = self._decisions
        if since:
            filtered = [d for d in filtered if d.timestamp > since]
        return filtered[-limit:] if limit else filtered

    def get_stats(self) -> dict[str, Any]:
        """Get classification statistics.

        Returns:
            Dict with stats (total decisions, intent distribution, agent distribution)
        """
        if not self._decisions:
            return {"total": 0}

        intents: dict[str, int] = {}
        agents: dict[str, int] = {}
        for d in self._decisions:
            intents[d.classified_intent] = intents.get(d.classified_intent, 0) + 1
            agents[d.selected_agent] = agents.get(d.selected_agent, 0) + 1

        return {
            "total": len(self._decisions),
            "intent_distribution": intents,
            "agent_distribution": agents,
        }

    def clear(self) -> None:
        """Clear all logged decisions."""
        self._decisions.clear()

    def enable_audit(self) -> None:
        """Enable audit logging."""
        self._audit_enabled = True

    def disable_audit(self) -> None:
        """Disable audit logging."""
        self._audit_enabled = False
