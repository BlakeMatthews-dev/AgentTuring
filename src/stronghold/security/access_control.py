"""Agent-level access control (migration 012).

Restricts invocation of agents whose visibility is "restricted" to callers
in the agent's access_grant allowlist. IdentityKind.SYSTEM callers bypass.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from stronghold.types.auth import AuthContext, IdentityKind

logger = logging.getLogger("stronghold.security.access_control")


def check_agent_access(
    agent_name: str,
    visibility: str,
    access_grant: dict[str, Any],
    auth: AuthContext,
) -> None:
    """Raise 403 if the caller is not allowed to invoke this agent."""
    if visibility != "restricted":
        return
    if auth.kind == IdentityKind.SYSTEM:
        return
    users = access_grant.get("users") or []
    if auth.user_id in users:
        return
    service_accounts = access_grant.get("service_accounts") or []
    if auth.kind == IdentityKind.SERVICE_ACCOUNT and auth.user_id in service_accounts:
        return
    orgs = access_grant.get("orgs") or []
    if auth.org_id in orgs:
        return

    logger.warning(
        "Access denied: user=%s kind=%s tried to invoke restricted agent '%s'",
        auth.user_id, auth.kind, agent_name,
    )
    raise HTTPException(
        status_code=403,
        detail={"error": "agent_not_accessible", "agent": agent_name},
    )


def is_agent_visible(
    visibility: str,
    access_grant: dict[str, Any],
    auth: AuthContext,
) -> bool:
    """Return True if the agent should appear in GET /agents listings."""
    if visibility != "restricted":
        return True
    if auth.kind == IdentityKind.SYSTEM:
        return True
    users = access_grant.get("users") or []
    if auth.user_id in users:
        return True
    service_accounts = access_grant.get("service_accounts") or []
    if auth.kind == IdentityKind.SERVICE_ACCOUNT and auth.user_id in service_accounts:
        return True
    orgs = access_grant.get("orgs") or []
    if auth.org_id in orgs:
        return True
    return False
