"""Task acceptance policy — Casbin gate for A2A task creation.

ADR-K8S-030: policy surface at A2A boundary for task creation
gating with budget enforcement integrated with six-tier priorities.

Evaluates: (user, org, agent, "task_create") → allow/deny
Budget rules: (user, org, budget_tier, "budget") → allow/deny
"""

from __future__ import annotations

import logging
import math
from typing import Protocol, runtime_checkable

logger = logging.getLogger("stronghold.security.task_policy")


@runtime_checkable
class TaskAcceptancePolicy(Protocol):
    """Protocol for task creation policy enforcement."""

    def check_task_creation(
        self,
        user_id: str,
        org_id: str,
        agent_name: str,
    ) -> bool: ...

    def check_budget(
        self,
        user_id: str,
        org_id: str,
        priority_tier: str,
        token_budget: float | None,
        cost_budget: float | None,
        wall_clock_seconds: float | None,
    ) -> bool: ...


class InMemoryTaskAcceptancePolicy:
    """In-memory task acceptance policy with configurable limits.

    Default: allow all task creation, enforce budget limits per priority tier.
    """

    def __init__(self) -> None:
        self._denied_agents: set[tuple[str, str, str]] = set()  # (user, org, agent)
        self._base_budget: dict[str, dict[str, float]] = {
            # Base budget tiers (P0-P5) for logarithmic scaling
            "P0": {"max_cost": 10.0, "max_seconds": 300},
            "P1": {"max_cost": 5.0, "max_seconds": 600},
            "P2": {"max_cost": 20.0, "max_seconds": 3600},
            "P3": {"max_cost": 10.0, "max_seconds": 1800},
            "P4": {"max_cost": 50.0, "max_seconds": 7200},
            "P5": {"max_cost": 100.0, "max_seconds": 14400},
        }
        self._base_tokens_per_tier: dict[str, float] = {
            # Base token counts before logarithmic scaling
            # P0: highest priority, gets most tokens
            "P0": 200_000,
            "P1": 150_000,
            "P2": 100_000,
            "P3": 75_000,
            "P4": 50_000,
            "P5": 25_000,
        }

    def _calculate_token_budget(self, priority_tier: str) -> float:
        """Calculate token budget using logarithmic scaling.

        Formula: max_tokens = base_tokens / log2(priority + 2)

        Where:
        - base_tokens is the agent's standard token budget
        - priority is 0 for P0, 1 for P1, etc.
        - P0 gets base_tokens / 1.41
        - P2 gets base_tokens / 2.0
        - P5 gets base_tokens / 2.83

        Args:
            priority_tier: Priority tier (P0-P5)

        Returns:
            Scaled token budget
        """
        base_tokens = self._base_tokens_per_tier.get(priority_tier, 100_000)
        priority = int(priority_tier[1:])  # Extract number from "P0", "P1", etc.
        return base_tokens / math.log2(priority + 2)

    def deny_agent(self, user_id: str, org_id: str, agent_name: str) -> None:
        self._denied_agents.add((user_id, org_id, agent_name))

    def set_budget_limit(
        self,
        tier: str,
        max_tokens: float | None = None,
        max_cost: float | None = None,
        max_seconds: float | None = None,
    ) -> None:
        if max_tokens is not None:
            self._base_tokens_per_tier[tier] = max_tokens
        if max_cost is not None:
            self._base_budget[tier]["max_cost"] = max_cost
        if max_seconds is not None:
            self._base_budget[tier]["max_seconds"] = max_seconds

    def check_task_creation(
        self,
        user_id: str,
        org_id: str,
        agent_name: str,
    ) -> bool:
        if (user_id, org_id, agent_name) in self._denied_agents:
            logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                "Task creation DENIED: user=%s org=%s agent=%s",
                user_id,
                org_id,
                agent_name,
            )
            return False
        return True

    def check_budget(
        self,
        user_id: str,
        org_id: str,
        priority_tier: str,
        token_budget: float | None = None,
        cost_budget: float | None = None,
        wall_clock_seconds: float | None = None,
    ) -> bool:
        # Reject unknown tiers (security: prevent bypass via invalid tier names)
        if priority_tier not in self._base_budget:
            logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                "Budget DENIED: user=%s org=%s unknown tier=%s",
                user_id,
                org_id,
                priority_tier,
            )
            return False
        limits = self._base_budget[priority_tier]

        if token_budget is not None:
            max_tokens = self._calculate_token_budget(priority_tier)
            if token_budget > max_tokens:
                logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                    "Budget DENIED: user=%s org=%s tier=%s token_count=%s > max=%s",
                    user_id,
                    org_id,
                    priority_tier,
                    token_budget,
                    max_tokens,
                )
                return False

        if cost_budget is not None and cost_budget > limits.get("max_cost", float("inf")):
            logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                "Budget DENIED: user=%s org=%s tier=%s cost=%s > max=%s",
                user_id,
                org_id,
                priority_tier,
                cost_budget,
                limits["max_cost"],
            )
            return False

        max_seconds = limits.get("max_seconds", float("inf"))
        if wall_clock_seconds is not None and wall_clock_seconds > max_seconds:
            logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                "Budget DENIED: user=%s org=%s tier=%s seconds=%s > max=%s",
                user_id,
                org_id,
                priority_tier,
                wall_clock_seconds,
                limits["max_seconds"],
            )
            return False

        return True
