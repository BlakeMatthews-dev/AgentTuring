"""Task acceptance policy — Casbin gate for A2A task creation.

ADR-K8S-030: policy surface at the A2A boundary for task creation
gating with budget enforcement integrated with six-tier priorities.

Evaluates: (user, org, agent, "task_create") → allow/deny
Budget rules: (user, org, budget_tier, "budget") → allow/deny
"""

from __future__ import annotations

import logging
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
        self._budget_limits: dict[str, dict[str, float]] = {
            # Default per-tier budget limits
            "P0": {"max_tokens": 100_000, "max_cost": 10.0, "max_seconds": 300},
            "P1": {"max_tokens": 50_000, "max_cost": 5.0, "max_seconds": 600},
            "P2": {"max_tokens": 200_000, "max_cost": 20.0, "max_seconds": 3600},
            "P3": {"max_tokens": 100_000, "max_cost": 10.0, "max_seconds": 1800},
            "P4": {"max_tokens": 500_000, "max_cost": 50.0, "max_seconds": 7200},
            "P5": {"max_tokens": 1_000_000, "max_cost": 100.0, "max_seconds": 14400},
        }

    def deny_agent(self, user_id: str, org_id: str, agent_name: str) -> None:
        self._denied_agents.add((user_id, org_id, agent_name))

    def set_budget_limit(
        self,
        tier: str,
        max_tokens: float | None = None,
        max_cost: float | None = None,
        max_seconds: float | None = None,
    ) -> None:
        limits = self._budget_limits.setdefault(tier, {})
        if max_tokens is not None:
            limits["max_tokens"] = max_tokens
        if max_cost is not None:
            limits["max_cost"] = max_cost
        if max_seconds is not None:
            limits["max_seconds"] = max_seconds

    def check_task_creation(
        self,
        user_id: str,
        org_id: str,
        agent_name: str,
    ) -> bool:
        if (user_id, org_id, agent_name) in self._denied_agents:
            logger.warning(
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
        limits = self._budget_limits.get(priority_tier, {})
        if not limits:
            return True

        if token_budget is not None and token_budget > limits.get("max_tokens", float("inf")):
            logger.warning(
                "Budget DENIED: user=%s org=%s tier=%s tokens=%s > max=%s",
                user_id,
                org_id,
                priority_tier,
                token_budget,
                limits["max_tokens"],
            )
            return False

        if cost_budget is not None and cost_budget > limits.get("max_cost", float("inf")):
            logger.warning(
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
            logger.warning(
                "Budget DENIED: user=%s org=%s tier=%s seconds=%s > max=%s",
                user_id,
                org_id,
                priority_tier,
                wall_clock_seconds,
                limits["max_seconds"],
            )
            return False

        return True
