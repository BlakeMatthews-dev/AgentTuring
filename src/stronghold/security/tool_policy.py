"""Tool Policy layer — Casbin-based access control for tool calls and tasks.

ADR-K8S-019: two policy gates evaluated at runtime:
  1. Per-tool-call: (user, org, tool, "tool_call") -> allow/deny
  2. Per-task-creation: (user, org, agent, "task_create") -> allow/deny

Policy data loaded from CSV file with runtime updates possible.
Decisions are logged for audit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import casbin

logger = logging.getLogger("stronghold.security.tool_policy")


@runtime_checkable
class ToolPolicyProtocol(Protocol):
    """Protocol for tool/task policy enforcement."""

    def check_tool_call(
        self, user_id: str, org_id: str, tool_name: str,
    ) -> bool: ...

    def check_task_creation(
        self, user_id: str, org_id: str, agent_name: str,
    ) -> bool: ...


class CasbinToolPolicy:
    """Casbin-backed tool policy engine.

    Uses a PERM model with request (sub, org, obj, act) and
    policy entries with explicit allow/deny effect.
    """

    def __init__(self, model_path: str, policy_path: str) -> None:
        self._model_path = model_path
        self._policy_path = policy_path
        self._enforcer = casbin.Enforcer(model_path, policy_path)

    def check_tool_call(
        self, user_id: str, org_id: str, tool_name: str,
    ) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, tool_name, "tool_call")
        if not result:
            logger.warning(
                "Tool call DENIED: user=%s org=%s tool=%s",
                user_id, org_id, tool_name,
            )
        return result

    def check_task_creation(
        self, user_id: str, org_id: str, agent_name: str,
    ) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, agent_name, "task_create")
        if not result:
            logger.warning(
                "Task creation DENIED: user=%s org=%s agent=%s",
                user_id, org_id, agent_name,
            )
        return result

    def reload_policy(self) -> None:
        self._enforcer.load_policy()
        logger.info("Tool policy reloaded from %s", self._policy_path)

    def add_policy(
        self, sub: str, org: str, obj: str, act: str, eft: str = "allow",
    ) -> bool:
        result: bool = self._enforcer.add_policy(sub, org, obj, act, eft)
        return result

    def remove_policy(
        self, sub: str, org: str, obj: str, act: str, eft: str = "allow",
    ) -> bool:
        result: bool = self._enforcer.remove_policy(sub, org, obj, act, eft)
        return result


def create_tool_policy(
    model_path: str | None = None,
    policy_path: str | None = None,
) -> CasbinToolPolicy:
    """Create a CasbinToolPolicy with default paths."""
    config_dir = Path("config")
    if model_path is None:
        model_path = str(config_dir / "tool_policy_model.conf")
    if policy_path is None:
        policy_path = str(config_dir / "tool_policy.csv")
    return CasbinToolPolicy(model_path, policy_path)
