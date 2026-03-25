"""Memory scope filtering for retrieval queries.

Hierarchy: GLOBAL > ORGANIZATION > TEAM > USER > AGENT > SESSION
Mirrors the identity model: Organization → Team → User/ServiceAccount.
"""

from __future__ import annotations

from stronghold.types.memory import MemoryScope


def build_scope_filter(
    agent_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    org_id: str | None = None,
) -> list[tuple[str, str | None]]:
    """Build a list of (scope, value) filters for memory retrieval.

    Returns conditions that should be OR'd together:
    - global memories (always visible)
    - organization memories (if org_id provided)
    - team memories (if team_id provided)
    - user memories (if user_id provided)
    - agent memories (if agent_id provided)
    """
    filters: list[tuple[str, str | None]] = [
        (MemoryScope.GLOBAL, None),
    ]
    if org_id:
        filters.append((MemoryScope.ORGANIZATION, org_id))
    if team_id:
        filters.append((MemoryScope.TEAM, team_id))
    if user_id:
        filters.append((MemoryScope.USER, user_id))
    if agent_id:
        filters.append((MemoryScope.AGENT, agent_id))
    return filters
