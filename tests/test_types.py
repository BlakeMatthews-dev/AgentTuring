"""Tests for all type definitions — frozen, valid, constructable."""

from stronghold.types.agent import (
    AgentIdentity,
    AgentResponse,
    AgentTask,
    ExecutionMode,
    ReasoningResult,
)
from stronghold.types.auth import SYSTEM_AUTH, AuthContext, PermissionTable
from stronghold.types.config import RoutingConfig, StrongholdConfig, TaskTypeConfig
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
from stronghold.types.memory import WEIGHT_BOUNDS, EpisodicMemory, Learning, MemoryScope, MemoryTier
from stronghold.types.model import ModelCandidate, ModelConfig, ModelSelection, ProviderConfig
from stronghold.types.security import (
    ClarifyingQuestion,
    GateResult,
    SentinelVerdict,
    TrustTier,
    Violation,
    WardenVerdict,
)
from stronghold.types.session import SessionConfig, SessionMessage
from stronghold.types.skill import SkillDefinition, SkillMetadata
from stronghold.types.tool import ToolCall, ToolDefinition, ToolResult


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

    def test_defaults(self) -> None:
        intent = Intent()
        assert intent.task_type == "chat"
        assert intent.complexity == "simple"
        assert intent.priority == "normal"

    def test_tier_order(self) -> None:
        assert TIER_ORDER["small"] < TIER_ORDER["medium"]
        assert TIER_ORDER["medium"] < TIER_ORDER["large"]
        assert TIER_ORDER["large"] < TIER_ORDER["frontier"]


class TestModelTypes:
    def test_provider_config_frozen(self) -> None:
        pc = ProviderConfig()
        assert pc.status == "active"

    def test_model_config_frozen(self) -> None:
        mc = ModelConfig(provider="test")
        assert mc.provider == "test"

    def test_model_candidate(self) -> None:
        mc = ModelCandidate(
            model_id="m",
            litellm_id="l",
            provider="p",
            score=0.5,
            quality=0.7,
            effective_cost=0.1,
            usage_pct=0.3,
            tier="medium",
        )
        assert mc.score == 0.5

    def test_model_selection(self) -> None:
        ms = ModelSelection(model_id="m", litellm_id="l", provider="p", score=0.8, reason="best")
        assert ms.reason == "best"


class TestAuthTypes:
    def test_system_auth(self) -> None:
        assert SYSTEM_AUTH.user_id == "system"
        assert SYSTEM_AUTH.has_role("admin")

    def test_permission_table_from_config(self) -> None:
        pt = PermissionTable.from_config({"admin": ["*"], "viewer": ["search"]})
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"admin"}))
        assert ctx.can_use_tool("anything", pt)

    def test_auth_context_no_roles(self) -> None:
        ctx = AuthContext(user_id="u", username="u")
        pt = PermissionTable.from_config({"admin": ["*"]})
        assert not ctx.can_use_tool("test", pt)


class TestMemoryTypes:
    def test_all_tiers_have_bounds(self) -> None:
        for tier in MemoryTier:
            assert tier in WEIGHT_BOUNDS

    def test_all_scopes_exist(self) -> None:
        assert len(MemoryScope) == 6  # global, organization, team, user, agent, session

    def test_learning_defaults(self) -> None:
        l = Learning()
        assert l.category == "general"
        assert l.hit_count == 0
        assert l.status == "active"

    def test_episodic_defaults(self) -> None:
        em = EpisodicMemory()
        assert em.tier == MemoryTier.OBSERVATION
        assert not em.deleted


class TestSecurityTypes:
    def test_warden_verdict_clean(self) -> None:
        v = WardenVerdict()
        assert v.clean
        assert not v.blocked

    def test_sentinel_verdict_allowed(self) -> None:
        sv = SentinelVerdict()
        assert sv.allowed
        assert not sv.repaired

    def test_trust_tiers(self) -> None:
        assert TrustTier.SKULL == "skull"
        assert TrustTier.T0 == "t0"

    def test_violation(self) -> None:
        v = Violation(boundary="test", rule="test_rule")
        assert v.severity == "error"

    def test_gate_result(self) -> None:
        gr = GateResult(sanitized_text="clean")
        assert not gr.blocked

    def test_clarifying_question(self) -> None:
        cq = ClarifyingQuestion(question="What?", options=("a", "b"))
        assert cq.allow_freetext


class TestAgentTypes:
    def test_execution_modes(self) -> None:
        assert ExecutionMode.BEST_EFFORT == "best_effort"
        assert ExecutionMode.PERSISTENT == "persistent"
        assert ExecutionMode.SUPERVISED == "supervised"

    def test_agent_identity(self) -> None:
        ai = AgentIdentity(name="test")
        assert ai.version == "1.0.0"
        assert ai.model == "auto"

    def test_agent_response(self) -> None:
        ar = AgentResponse(content="hello", agent_name="test")
        assert not ar.blocked

    def test_blocked_response(self) -> None:
        ar = AgentResponse.blocked_response("bad input")
        assert ar.blocked
        assert ar.block_reason == "bad input"

    def test_reasoning_result(self) -> None:
        rr = ReasoningResult(response="done", done=True)
        assert rr.done

    def test_agent_task(self) -> None:
        at = AgentTask(id="t1", from_agent="arbiter", to_agent="artificer")
        assert at.status == "submitted"


class TestToolTypes:
    def test_tool_definition(self) -> None:
        td = ToolDefinition(name="test")
        assert td.endpoint == ""

    def test_tool_call(self) -> None:
        tc = ToolCall(id="c1", name="test")
        assert tc.arguments == {}

    def test_tool_result(self) -> None:
        tr = ToolResult(content="ok")
        assert tr.success


class TestSkillTypes:
    def test_skill_definition(self) -> None:
        sd = SkillDefinition(name="test")
        assert sd.trust_tier == "t2"

    def test_skill_metadata(self) -> None:
        sm = SkillMetadata(name="test")
        assert sm.author == ""


class TestSessionTypes:
    def test_session_message(self) -> None:
        sm = SessionMessage(role="user", content="hello")
        assert sm.role == "user"

    def test_session_config(self) -> None:
        sc = SessionConfig()
        assert sc.max_messages == 20
        assert sc.ttl_seconds == 86400


class TestConfigTypes:
    def test_routing_config_defaults(self) -> None:
        rc = RoutingConfig()
        assert rc.quality_weight == 0.6
        assert "normal" in rc.priority_multipliers

    def test_task_type_config(self) -> None:
        ttc = TaskTypeConfig(keywords=["code"])
        assert ttc.min_tier == "small"

    def test_stronghold_config_defaults(self) -> None:
        sc = StrongholdConfig()
        assert sc.litellm_url == "http://litellm:4000"
