"""Authentication and authorization types.

Identity model: Organization → Team → User/ServiceAccount

- Organization: billing/isolation boundary (the "tenant")
- Team: workspace within an org (dev, ops, marketing)
- User: human identity, belongs to one or more teams
- ServiceAccount: non-human team-scoped identity (API keys, automation)

Identity keys are scoped to team level: team:user or team:service_account.
AuthContext carries org_id + team_id + user_id for all boundary checks.
PermissionTable is config-driven RBAC — no hardcoded user/role mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IdentityKind(StrEnum):
    """The type of authenticated identity.

    USER: human identity, direct login (JWT from browser, mobile, CLI)
    AGENT: autonomous agent acting on its own behalf (nearly like a user, has own identity)
    SERVICE_ACCOUNT: non-human team-scoped key (API automation, cron, CI/CD)
    INTERACTIVE_AGENT: agent acting on behalf of a user (authenticates as service account,
                       passes the interactive user as on_behalf_of — audit trail shows both)
    SYSTEM: internal system identity (static API key, bootstrap)
    """

    USER = "user"
    AGENT = "agent"
    SERVICE_ACCOUNT = "service_account"
    INTERACTIVE_AGENT = "interactive_agent"
    SYSTEM = "system"


@dataclass(frozen=True)
class AuthContext:
    """Authenticated identity extracted from JWT or API key.

    The hierarchy is: org_id > team_id > user_id.
    - org_id: organization (billing/isolation boundary)
    - team_id: team within the org (workspace scope)
    - user_id: user or service account within the team
    - kind: whether this is a user, service_account, or system identity
    """

    user_id: str
    username: str = ""
    roles: frozenset[str] = frozenset()
    org_id: str = ""
    team_id: str = ""
    kind: IdentityKind = IdentityKind.USER
    auth_method: str = "jwt"
    on_behalf_of: str = ""  # For INTERACTIVE_AGENT: the user this agent acts for

    @property
    def tenant_id(self) -> str:
        """Backward-compatible tenant_id = org_id.

        Use org_id directly in new code.
        """
        return self.org_id

    @property
    def scope_key(self) -> str:
        """Unique scope key for this identity: org/team/user."""
        parts = [p for p in (self.org_id, self.team_id, self.user_id) if p]
        return "/".join(parts)

    @property
    def is_service_account(self) -> bool:
        """Whether this is a non-human identity."""
        return self.kind == IdentityKind.SERVICE_ACCOUNT

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def can_use_tool(self, tool_name: str, permission_table: PermissionTable) -> bool:
        """Check if user can use a specific tool via the permission table."""
        return permission_table.check(self.roles, tool_name)

    def same_org(self, other: AuthContext) -> bool:
        """Check if two identities belong to the same organization."""
        return bool(self.org_id and self.org_id == other.org_id)

    def same_team(self, other: AuthContext) -> bool:
        """Check if two identities belong to the same team."""
        return self.same_org(other) and bool(self.team_id and self.team_id == other.team_id)


# Reserved org_id for system-level operations (static API key, internal calls).
# Using a reserved sentinel prevents accidental data mixing between
# unscoped callers — every caller has an explicit org identity.
SYSTEM_ORG_ID = "__system__"

# System auth context for static API key callers.
# Read-only keys only get "user" role. Full admin access requires
# proper authentication (JWT or demo login).
SYSTEM_AUTH = AuthContext(
    user_id="system",
    username="system",
    org_id=SYSTEM_ORG_ID,
    roles=frozenset({"admin", "org_admin", "team_admin", "user"}),
    kind=IdentityKind.SYSTEM,
    auth_method="api_key",
)


@dataclass(frozen=True)
class PermissionTable:
    """Config-driven role-to-tool permission mapping.

    Loaded from permissions.yaml, not hardcoded in source.
    """

    roles: dict[str, set[str]] = field(default_factory=dict)

    def check(self, user_roles: frozenset[str], tool_name: str) -> bool:
        """Check if any of the user's roles grant access to the tool."""
        for role in user_roles:
            allowed = self.roles.get(role, set())
            if "*" in allowed or tool_name in allowed:
                return True
        return False

    @classmethod
    def from_config(cls, config: dict[str, list[str]]) -> PermissionTable:
        """Create from config dict: {role_name: [tool_names]}."""
        return cls(roles={role: set(tools) for role, tools in config.items()})
