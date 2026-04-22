"""Behavioral tests for type definitions.

Pure dataclass-field round-trips (``x = Model(a=1); assert x.a == 1``)
are not included here — they test nothing beyond Python's own attribute
machinery. This file only keeps tests that exercise observable behavior:
error hierarchies, frozen/immutable invariants, factory methods, scope
enumerations, and tier ordering relations.
"""

from stronghold.types.agent import (
    AgentIdentity,
    AgentResponse,
)
from stronghold.types.auth import SYSTEM_AUTH, AuthContext, PermissionTable
from stronghold.types.errors import (
    AuthError,
    ClassificationError,
    ConfigError,
    InjectionError,
    NoModelsError,
    PermissionDeniedError,
    QuotaReserveError,
    RoutingError,
    SecurityError,
    SkillError,
    StrongholdError,
    TokenExpiredError,
    ToolError,
    TrustViolationError,
)
from stronghold.types.intent import TIER_ORDER, Intent
from stronghold.types.memory import WEIGHT_BOUNDS, MemoryScope, MemoryTier


class TestErrorHierarchy:
    def test_all_errors_have_code(self) -> None:
        for cls in [
            StrongholdError,
            RoutingError,
            QuotaReserveError,
            NoModelsError,
            ClassificationError,
            AuthError,
            TokenExpiredError,
            PermissionDeniedError,
            ToolError,
            SecurityError,
            InjectionError,
            TrustViolationError,
            ConfigError,
            SkillError,
        ]:
            err = cls("test")
            assert err.code
            assert err.detail == "test"

    def test_error_string_includes_code(self) -> None:
        err = QuotaReserveError("all in reserve")
        assert "QUOTA_RESERVE_BLOCKED" in str(err)

    def test_error_inheritance(self) -> None:
        assert issubclass(QuotaReserveError, RoutingError)
        assert issubclass(RoutingError, StrongholdError)
        assert issubclass(InjectionError, SecurityError)


class TestIntent:
    def test_frozen(self) -> None:
        intent = Intent()
        try:
            intent.task_type = "code"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass

    def test_tier_order_is_strictly_ascending(self) -> None:
        # Routing relies on this ordering to decide if a model's tier is
        # "at least" the requested tier. A silent reorder would silently
        # promote/demote every routing decision.
        assert TIER_ORDER["small"] < TIER_ORDER["medium"]
        assert TIER_ORDER["medium"] < TIER_ORDER["large"]
        assert TIER_ORDER["large"] < TIER_ORDER["frontier"]


class TestAuthTypes:
    def test_system_auth_has_admin_role(self) -> None:
        assert SYSTEM_AUTH.user_id == "system"
        assert SYSTEM_AUTH.has_role("admin")

    def test_permission_table_wildcard_admits_any_tool(self) -> None:
        pt = PermissionTable.from_config({"admin": ["*"], "viewer": ["search"]})
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"admin"}))
        # Admin wildcard: tool name doesn't matter.
        assert ctx.can_use_tool("anything", pt)

    def test_auth_context_without_roles_denied(self) -> None:
        ctx = AuthContext(user_id="u", username="u")
        pt = PermissionTable.from_config({"admin": ["*"]})
        assert not ctx.can_use_tool("test", pt)


class TestMemoryTypes:
    def test_all_tiers_have_weight_bounds(self) -> None:
        # Each MemoryTier must have a bound so ranking logic never KeyErrors.
        for tier in MemoryTier:
            assert tier in WEIGHT_BOUNDS

    def test_memory_scope_is_full_hierarchy(self) -> None:
        # The scope enum defines the auth hierarchy. Widening or narrowing
        # it silently would change isolation semantics, so pin the
        # full set here rather than just its size.
        assert {s.name for s in MemoryScope} == {
            "GLOBAL",
            "ORGANIZATION",
            "TEAM",
            "USER",
            "AGENT",
            "SESSION",
        }


class TestAgentPriorityTier:
    """AgentIdentity.priority_tier (issue #892)."""

    def test_explicit_priority_tier_round_trips(self) -> None:
        for tier in ("P0", "P1", "P2", "P3", "P4", "P5"):
            ai = AgentIdentity(name="test", priority_tier=tier)
            assert ai.priority_tier == tier

    def test_priority_tier_is_frozen(self) -> None:
        import pytest

        ai = AgentIdentity(name="test", priority_tier="P0")
        with pytest.raises(AttributeError):
            ai.priority_tier = "P1"  # type: ignore[misc]


class TestAgentResponse:
    """AgentResponse factory methods and blocked-state invariant."""

    def test_blocked_response_factory_sets_blocked_and_reason(self) -> None:
        ar = AgentResponse.blocked_response("bad input")
        assert ar.blocked
        assert ar.block_reason == "bad input"
        # A blocked response carries no content — the caller must surface
        # the block_reason instead.
        assert ar.content == ""
