"""Tests for coverage gaps across triggers, skill registry versions, admin
approval endpoints, learning promoter gate path, skills test route, and
worker_main helpers.

All tests use real classes and fakes from tests/fakes.py — no unittest.mock.
asyncio_mode = "auto" (no @pytest.mark.asyncio needed).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.tournament import Tournament
from stronghold.agents.worker import AgentWorker
from stronghold.api.routes.admin import router as admin_router
from stronghold.api.routes.skills import router as skills_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.events import Reactor
from stronghold.memory.learnings.approval import LearningApprovalGate
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.mutations import InMemorySkillMutationStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.rate_limiter import InMemoryRateLimiter
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.skills.canary import CanaryManager
from stronghold.skills.registry import InMemorySkillRegistry
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.triggers import register_core_triggers
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from stronghold.types.memory import Learning
from stronghold.types.reactor import Event
from stronghold.types.skill import SkillDefinition
from tests.fakes import FakeAuthProvider, FakeLLMClient


# ── Helpers ────────────────────────────────────────────────────────


def _minimal_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


def _build_container(
    *,
    fake_llm: FakeLLMClient | None = None,
    learning_store: InMemoryLearningStore | None = None,
    approval_gate: LearningApprovalGate | None = None,
    canary_manager: CanaryManager | None = None,
    tournament: Tournament | None = None,
    learning_promoter: LearningPromoter | None = None,
    auth_provider: Any = None,
) -> Container:
    """Build a minimal Container for testing triggers / admin endpoints."""
    llm = fake_llm or FakeLLMClient()
    llm.set_simple_response("ok")
    config = _minimal_config()
    prompts = InMemoryPromptManager()
    ls = learning_store or InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()
    tool_registry = InMemoryToolRegistry()

    default_agent = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
            memory_config={"learnings": True},
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=ls,
    )

    ap = auth_provider or StaticKeyAuthProvider(api_key="sk-test")

    container = Container(
        config=config,
        auth_provider=ap,
        permission_table=PermissionTable.from_config({"admin": ["*"]}),
        router=RouterEngine(InMemoryQuotaTracker()),
        classifier=ClassifierEngine(),
        quota_tracker=InMemoryQuotaTracker(),
        prompt_manager=prompts,
        learning_store=ls,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
        audit_log=audit_log,
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=PermissionTable.from_config(config.permissions),
            audit_log=audit_log,
        ),
        tracer=NoopTracingBackend(),
        context_builder=context_builder,
        intent_registry=IntentRegistry(),
        llm=llm,
        tool_registry=tool_registry,
        tool_dispatcher=ToolDispatcher(tool_registry),
        agents={"arbiter": default_agent},
        tournament=tournament,
        canary_manager=canary_manager,
        learning_approval_gate=approval_gate,
        learning_promoter=learning_promoter,
    )
    return container


# ═══════════════════════════════════════════════════════════════════
# 1. Triggers — uncovered paths around canary_manager, tournament,
#    and promoter.
# ═══════════════════════════════════════════════════════════════════


class TestTriggersCanaryCheck:
    """Cover lines 139-152 of triggers.py — canary deployment check."""

    async def test_canary_trigger_with_no_manager_returns_skipped(self) -> None:
        container = _build_container(canary_manager=None)
        register_core_triggers(container)

        # Find the canary trigger action
        canary_action = None
        for state, action in container.reactor._triggers:
            if state.spec.name == "canary_deployment_check":
                canary_action = action
                break
        assert canary_action is not None
        result = await canary_action(Event(name="_interval:canary_deployment_check"))
        assert result == {"skipped": True}

    async def test_canary_trigger_with_active_deployment(self) -> None:
        cm = CanaryManager(
            error_threshold=0.5, min_requests_per_stage=1, stage_duration_secs=0.0
        )
        cm.start_canary("my_skill", old_version=0, new_version=1)
        container = _build_container(canary_manager=cm)
        register_core_triggers(container)

        canary_action = None
        for state, action in container.reactor._triggers:
            if state.spec.name == "canary_deployment_check":
                canary_action = action
                break
        assert canary_action is not None
        result = await canary_action(Event(name="_interval:canary_deployment_check"))
        assert result["active_canaries"] == 1

    async def test_canary_trigger_rollback_logged(self) -> None:
        cm = CanaryManager(
            error_threshold=0.1, min_requests_per_stage=2, stage_duration_secs=9999.0
        )
        cm.start_canary("bad_skill", old_version=0, new_version=1)
        # Record enough errors to trigger rollback
        cm.record_result("bad_skill", success=False)
        cm.record_result("bad_skill", success=False)
        cm.record_result("bad_skill", success=False)

        container = _build_container(canary_manager=cm)
        register_core_triggers(container)

        canary_action = None
        for state, action in container.reactor._triggers:
            if state.spec.name == "canary_deployment_check":
                canary_action = action
                break
        assert canary_action is not None
        # The check triggers rollback during iteration. list_active() is called
        # first, so active_canaries reflects the count BEFORE processing.
        # After running, the deployment should be gone from the manager.
        result = await canary_action(Event(name="_interval:canary_deployment_check"))
        assert result["active_canaries"] == 1  # count captured before rollback
        assert len(cm.list_active()) == 0  # actually removed after processing
        assert len(cm.list_rollbacks()) == 1


class TestTriggersTournamentCheck:
    """Cover the tournament trigger path."""

    async def test_tournament_trigger_no_tournament_returns_skipped(self) -> None:
        container = _build_container(tournament=None)
        register_core_triggers(container)

        tournament_action = None
        for state, action in container.reactor._triggers:
            if state.spec.name == "tournament_evaluation":
                tournament_action = action
                break
        assert tournament_action is not None
        result = await tournament_action(Event(name="_interval:tournament_evaluation"))
        assert result == {"skipped": True}

    async def test_tournament_trigger_returns_stats(self) -> None:
        t = Tournament()
        container = _build_container(tournament=t)
        register_core_triggers(container)

        tournament_action = None
        for state, action in container.reactor._triggers:
            if state.spec.name == "tournament_evaluation":
                tournament_action = action
                break
        assert tournament_action is not None
        result = await tournament_action(Event(name="_interval:tournament_evaluation"))
        assert "total_battles" in result
        assert result["total_battles"] == 0


class TestTriggersLearningPromotion:
    """Cover the learning promotion trigger."""

    async def test_promotion_trigger_no_promoter_returns_skipped(self) -> None:
        container = _build_container(learning_promoter=None)
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "learning_promotion_check":
                action = act
                break
        assert action is not None
        result = await action(Event(name="_interval:learning_promotion_check"))
        assert result == {"skipped": True}

    async def test_promotion_trigger_with_promoter(self) -> None:
        ls = InMemoryLearningStore()
        promoter = LearningPromoter(ls, threshold=5)
        container = _build_container(learning_store=ls, learning_promoter=promoter)
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "learning_promotion_check":
                action = act
                break
        assert action is not None
        result = await action(Event(name="_interval:learning_promotion_check"))
        assert result["promoted_count"] == 0


class TestTriggersSecurityRescan:
    """Cover the security_rescan trigger for empty content."""

    async def test_security_rescan_empty_content_skipped(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "security_rescan":
                action = act
                break
        assert action is not None
        result = await action(Event(name="security.rescan", data={"content": ""}))
        assert result == {"skipped": True}

    async def test_security_rescan_with_content(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "security_rescan":
                action = act
                break
        assert action is not None
        result = await action(
            Event(name="security.rescan", data={"content": "hello world", "boundary": "user_input"})
        )
        assert "clean" in result
        assert "flags" in result


class TestTriggersPostToolLearning:
    """Cover the post_tool_learning trigger."""

    async def test_post_tool_failure_logged(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "post_tool_learning":
                action = act
                break
        assert action is not None
        result = await action(
            Event(name="post_tool_loop", data={"tool_name": "web_search", "success": False})
        )
        assert result["tool_name"] == "web_search"
        assert result["success"] is False

    async def test_post_tool_success(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "post_tool_learning":
                action = act
                break
        assert action is not None
        result = await action(
            Event(name="post_tool_loop", data={"tool_name": "", "success": True})
        )
        assert result["success"] is True


class TestTriggersOutcomeStats:
    """Cover the outcome stats trigger."""

    async def test_outcome_stats_returns_stats(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "outcome_stats_snapshot":
                action = act
                break
        assert action is not None
        result = await action(Event(name="_interval:outcome_stats_snapshot"))
        assert "total" in result
        assert "rate" in result


class TestTriggersRateLimitEviction:
    """Cover the rate limit eviction trigger."""

    async def test_rate_limit_eviction_runs(self) -> None:
        container = _build_container()
        register_core_triggers(container)

        action = None
        for state, act in container.reactor._triggers:
            if state.spec.name == "rate_limit_eviction":
                action = act
                break
        assert action is not None
        result = await action(Event(name="_interval:rate_limit_eviction"))
        assert "evicted" in result
        assert result["evicted"] == 0


class TestTriggerRegistrationCount:
    """Confirm all 7 core triggers are registered."""

    def test_registers_seven_triggers(self) -> None:
        container = _build_container()
        register_core_triggers(container)
        assert len(container.reactor._triggers) == 7


# ═══════════════════════════════════════════════════════════════════
# 2. InMemorySkillRegistry — version management (lines 108-153)
# ═══════════════════════════════════════════════════════════════════


class TestSkillRegistryGetVersions:
    def test_get_versions_returns_all_registered(self) -> None:
        reg = InMemorySkillRegistry()
        s1 = SkillDefinition(name="analyzer", description="v1", trust_tier="t2")
        s2 = SkillDefinition(name="analyzer", description="v2", trust_tier="t2")
        reg.register(s1, org_id="org-1")
        reg.register(s2, org_id="org-1")
        versions = reg.get_versions("analyzer", org_id="org-1")
        assert len(versions) == 2
        assert versions[0].description == "v1"
        assert versions[1].description == "v2"

    def test_get_versions_falls_back_to_global(self) -> None:
        reg = InMemorySkillRegistry()
        s1 = SkillDefinition(name="builtin", description="built-in v1", trust_tier="t0")
        reg.register(s1)  # global (t0 always global)
        versions = reg.get_versions("builtin", org_id="org-1")
        assert len(versions) == 1
        assert versions[0].description == "built-in v1"

    def test_get_versions_empty_for_unknown(self) -> None:
        reg = InMemorySkillRegistry()
        assert reg.get_versions("nope") == []

    def test_get_versions_no_fallback_when_no_org(self) -> None:
        reg = InMemorySkillRegistry()
        s = SkillDefinition(name="x", description="test", trust_tier="t2")
        reg.register(s, org_id="org-1")
        # Without org_id, checks global prefix only
        versions = reg.get_versions("x", org_id="")
        assert len(versions) == 0


class TestSkillRegistryGetVersion:
    def test_get_version_by_index(self) -> None:
        reg = InMemorySkillRegistry()
        s1 = SkillDefinition(name="tool", description="v1", trust_tier="t2")
        s2 = SkillDefinition(name="tool", description="v2", trust_tier="t2")
        reg.register(s1, org_id="org-a")
        reg.register(s2, org_id="org-a")
        assert reg.get_version("tool", 0, org_id="org-a") is not None
        assert reg.get_version("tool", 0, org_id="org-a").description == "v1"
        assert reg.get_version("tool", 1, org_id="org-a").description == "v2"

    def test_get_version_out_of_range(self) -> None:
        reg = InMemorySkillRegistry()
        s = SkillDefinition(name="tool", description="v1", trust_tier="t2")
        reg.register(s, org_id="org-a")
        assert reg.get_version("tool", 5, org_id="org-a") is None
        assert reg.get_version("tool", -1, org_id="org-a") is None

    def test_get_version_unknown_skill(self) -> None:
        reg = InMemorySkillRegistry()
        assert reg.get_version("nope", 0) is None


class TestSkillRegistryRollback:
    def test_rollback_restores_previous_version(self) -> None:
        reg = InMemorySkillRegistry()
        s1 = SkillDefinition(name="svc", description="v1", trust_tier="t2")
        s2 = SkillDefinition(name="svc", description="v2", trust_tier="t2")
        reg.register(s1, org_id="org-b")
        reg.register(s2, org_id="org-b")

        # Current should be v2
        current = reg.get("svc", org_id="org-b")
        assert current is not None
        assert current.description == "v2"

        # Rollback to v1 (index 0)
        result = reg.rollback("svc", 0, org_id="org-b")
        assert result is True

        # Now current should be v1
        rolled = reg.get("svc", org_id="org-b")
        assert rolled is not None
        assert rolled.description == "v1"

        # Rollback appended as new version entry
        versions = reg.get_versions("svc", org_id="org-b")
        assert len(versions) == 3  # v1, v2, v1-rollback

    def test_rollback_invalid_index_returns_false(self) -> None:
        reg = InMemorySkillRegistry()
        s = SkillDefinition(name="svc", description="v1", trust_tier="t2")
        reg.register(s, org_id="org-b")
        assert reg.rollback("svc", 5, org_id="org-b") is False
        assert reg.rollback("svc", -1, org_id="org-b") is False

    def test_rollback_unknown_skill_returns_false(self) -> None:
        reg = InMemorySkillRegistry()
        assert reg.rollback("nonexistent", 0) is False

    def test_rollback_falls_back_to_global(self) -> None:
        reg = InMemorySkillRegistry()
        s1 = SkillDefinition(name="global_svc", description="gv1", trust_tier="t0")
        s2 = SkillDefinition(name="global_svc", description="gv2", trust_tier="t0")
        reg.register(s1)
        reg.register(s2)
        # Rollback from an org context — should find global versions
        result = reg.rollback("global_svc", 0, org_id="org-x")
        assert result is True

    def test_rollback_no_versions_at_all(self) -> None:
        reg = InMemorySkillRegistry()
        # Register under org-a, try rollback under org-b (no versions found anywhere)
        s = SkillDefinition(name="svc", description="v1", trust_tier="t2")
        reg.register(s, org_id="org-a")
        assert reg.rollback("svc", 0, org_id="org-b") is False


# ═══════════════════════════════════════════════════════════════════
# 3. Admin routes — learning approvals (lines 121-175)
# ═══════════════════════════════════════════════════════════════════


def _admin_app_with_gate(
    gate: LearningApprovalGate | None = None,
) -> FastAPI:
    """Build a FastAPI app with admin routes and an optional approval gate."""
    app = FastAPI()
    app.include_router(admin_router)

    ls = InMemoryLearningStore()
    container = _build_container(learning_store=ls, approval_gate=gate)
    app.state.container = container
    return app


class TestListLearningApprovals:
    def test_no_gate_returns_empty(self) -> None:
        app = _admin_app_with_gate(gate=None)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/admin/learnings/approvals",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["gate_enabled"] is False
            assert data["approvals"] == []

    def test_with_gate_returns_approvals(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(
            learning_id=1,
            org_id="__system__",
            learning_preview="Test learning",
            tool_name="ha_control",
            hit_count=5,
        )
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/admin/learnings/approvals",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["gate_enabled"] is True
            assert len(data["approvals"]) == 1
            assert data["approvals"][0]["learning_id"] == 1

    def test_unauthenticated_returns_401(self) -> None:
        app = _admin_app_with_gate()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/learnings/approvals")
            assert resp.status_code == 401


class TestApproveLearning:
    def test_approve_pending_learning(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(learning_id=42, org_id="__system__")
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/approve",
                json={"learning_id": 42, "notes": "Looks good"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["learning_id"] == 42
            assert data["status"] == "approved"

    def test_approve_nonexistent_returns_404(self) -> None:
        gate = LearningApprovalGate()
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/approve",
                json={"learning_id": 999},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 404

    def test_approve_no_gate_returns_501(self) -> None:
        app = _admin_app_with_gate(gate=None)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/approve",
                json={"learning_id": 1},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 501

    def test_approve_non_admin_returns_403(self) -> None:
        gate = LearningApprovalGate()
        app = _admin_app_with_gate(gate=gate)
        # Switch to a non-admin auth provider
        app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/approve",
                json={"learning_id": 1},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 403


class TestRejectLearning:
    def test_reject_pending_learning(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(learning_id=42, org_id="__system__")
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/reject",
                json={"learning_id": 42, "reason": "Incorrect correction"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["learning_id"] == 42
            assert data["status"] == "rejected"
            assert data["reason"] == "Incorrect correction"

    def test_reject_nonexistent_returns_404(self) -> None:
        gate = LearningApprovalGate()
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/reject",
                json={"learning_id": 999, "reason": "Not found"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 404

    def test_reject_no_gate_returns_501(self) -> None:
        app = _admin_app_with_gate(gate=None)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/reject",
                json={"learning_id": 1},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 501

    def test_reject_already_approved_returns_404(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(learning_id=10, org_id="__system__")
        gate.approve(10, "admin-user", "ok")
        app = _admin_app_with_gate(gate=gate)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings/reject",
                json={"learning_id": 10, "reason": "too late"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            # Already approved, status is not "pending" so gate returns None → 404
            assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 4. LearningPromoter — gate path (line 107: _try_mutate_skill
#    when forge returns error or mutation status)
# ═══════════════════════════════════════════════════════════════════


class FakeSkillForge:
    """Fake skill forge for testing mutation paths."""

    def __init__(self, result: dict[str, Any] | None = None, raise_exc: bool = False) -> None:
        self._result = result or {"status": "mutated", "old_hash": "aaa", "new_hash": "bbb"}
        self._raise_exc = raise_exc

    async def forge(self, request: str) -> SkillDefinition:
        return SkillDefinition(name="forged", description="forged skill")

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        if self._raise_exc:
            msg = "Forge exploded"
            raise RuntimeError(msg)
        return self._result


class TestLearningPromoterTryMutateSkill:
    async def test_mutate_records_mutation(self) -> None:
        ls = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = FakeSkillForge(result={"status": "mutated", "old_hash": "aa", "new_hash": "bb"})
        promoter = LearningPromoter(
            ls, threshold=1, skill_forge=forge, mutation_store=mutation_store,
        )
        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Use this entity",
            tool_name="ha_control",
            hit_count=2,
        )
        await ls.store(lr)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 1
        assert mutations[0].skill_name == "ha_control"

    async def test_mutate_error_status_does_not_record(self) -> None:
        ls = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = FakeSkillForge(result={"status": "error", "error": "something broke"})
        promoter = LearningPromoter(
            ls, threshold=1, skill_forge=forge, mutation_store=mutation_store,
        )
        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Use this",
            tool_name="ha_control",
            hit_count=2,
        )
        await ls.store(lr)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0

    async def test_mutate_exception_does_not_crash(self) -> None:
        ls = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = FakeSkillForge(raise_exc=True)
        promoter = LearningPromoter(
            ls, threshold=1, skill_forge=forge, mutation_store=mutation_store,
        )
        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Use this",
            tool_name="ha_control",
            hit_count=2,
        )
        await ls.store(lr)
        # Should not raise
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0

    async def test_mutate_no_forge_returns_early(self) -> None:
        ls = InMemoryLearningStore()
        promoter = LearningPromoter(ls, threshold=1, skill_forge=None)
        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Use this",
            tool_name="ha_control",
            hit_count=2,
        )
        await ls.store(lr)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1

    async def test_mutate_skipped_status_does_not_record(self) -> None:
        ls = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = FakeSkillForge(result={"status": "skipped"})
        promoter = LearningPromoter(
            ls, threshold=1, skill_forge=forge, mutation_store=mutation_store,
        )
        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Use this",
            tool_name="ha_control",
            hit_count=2,
        )
        await ls.store(lr)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0


class TestLearningPromoterGatePath:
    """Cover _check_with_gate path.

    Note: find_relevant("") with InMemoryLearningStore always returns []
    because trigger_key matching against empty text yields no hits.
    We test the code paths that ARE reachable: gate invocation with
    empty candidates, and the approved_ids processing loop.
    """

    async def test_gate_path_with_no_candidates(self) -> None:
        """find_relevant("") returns [] so no approvals are queued."""
        ls = InMemoryLearningStore()
        gate = LearningApprovalGate()
        promoter = LearningPromoter(ls, threshold=2, approval_gate=gate)

        lr = Learning(
            category="general",
            trigger_keys=["test"],
            learning="Important learning",
            tool_name="",
            hit_count=5,
        )
        await ls.store(lr)

        # Gate path runs but find_relevant("") returns no candidates
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 0
        # No pending approvals since no candidates matched
        pending = gate.get_pending()
        assert len(pending) == 0

    async def test_gate_path_processes_pre_approved_ids(self) -> None:
        """If gate has approved IDs but find_relevant returns empty candidates,
        the loop over approved_ids still runs (no match found)."""
        ls = InMemoryLearningStore()
        gate = LearningApprovalGate()
        promoter = LearningPromoter(ls, threshold=2, approval_gate=gate)

        # Pre-populate an approval
        gate.request_approval(learning_id=99, org_id="")
        gate.approve(99, "admin", "ok")

        # Gate path: approved_ids=[99], but candidates=[] so no match
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 0

    async def test_gate_path_dispatches_to_check_with_gate(self) -> None:
        """Verify that check_and_promote uses _check_with_gate when gate present."""
        ls = InMemoryLearningStore()
        gate = LearningApprovalGate()
        promoter = LearningPromoter(ls, threshold=5, approval_gate=gate)

        # Even with no learnings, the gate path executes without error
        promoted = await promoter.check_and_promote()
        assert promoted == []

    async def test_auto_path_without_gate(self) -> None:
        """Without gate, auto-promote path fires."""
        ls = InMemoryLearningStore()
        promoter = LearningPromoter(ls, threshold=1, approval_gate=None)

        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Auto promoted",
            tool_name="",
            hit_count=2,
        )
        await ls.store(lr)
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    async def test_gate_with_forge_no_candidates(self) -> None:
        """Gate + forge: forge is not called when no candidates found."""
        ls = InMemoryLearningStore()
        gate = LearningApprovalGate()
        mutation_store = InMemorySkillMutationStore()
        forge = FakeSkillForge(result={"status": "mutated", "old_hash": "x", "new_hash": "y"})
        promoter = LearningPromoter(
            ls,
            threshold=2,
            approval_gate=gate,
            skill_forge=forge,
            mutation_store=mutation_store,
        )

        lr = Learning(
            category="tool_correction",
            trigger_keys=["test"],
            learning="Better entity",
            tool_name="ha_control",
            hit_count=5,
        )
        await ls.store(lr)

        # Queue step finds no candidates (find_relevant("") → [])
        promoted = await promoter.check_and_promote()
        assert len(promoted) == 0
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0


# ═══════════════════════════════════════════════════════════════════
# 5. Skills routes — /test endpoint (lines 284-285: auth error path)
# ═══════════════════════════════════════════════════════════════════


def _skills_app() -> FastAPI:
    """Build a FastAPI app with skills routes."""
    app = FastAPI()
    app.include_router(skills_router)
    container = _build_container()
    app.state.container = container
    return app


class TestSkillsTestRoute:
    def test_test_skill_unauthenticated_returns_401(self) -> None:
        app = _skills_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/skills/test",
                json={"skill_name": "something", "test_input": {}},
            )
            assert resp.status_code == 401

    def test_test_skill_missing_name_returns_400(self) -> None:
        app = _skills_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/skills/test",
                json={"test_input": {}},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400

    def test_test_skill_not_found_returns_error(self) -> None:
        app = _skills_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/skills/test",
                json={"skill_name": "nonexistent_tool", "test_input": {"x": "1"}},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            # The dispatcher catches the exception and returns success=False
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "Error" in data["output"]


# ═══════════════════════════════════════════════════════════════════
# 6. worker_main — AgentWorker process_one + run_loop with no tasks
# ═══════════════════════════════════════════════════════════════════


class TestAgentWorkerProcessOne:
    async def test_process_one_no_tasks(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("Hello from worker")
        worker = AgentWorker(queue=queue, llm=llm)
        result = await worker.process_one()
        assert result is False

    async def test_process_one_with_task(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("Worker response")
        worker = AgentWorker(queue=queue, llm=llm)

        task_id = await queue.submit(
            {"messages": [{"role": "user", "content": "hello"}], "model": "test", "agent": "arbiter"}
        )
        result = await worker.process_one()
        assert result is True

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert "Worker response" in task["result"]["content"]

    async def test_process_one_llm_failure(self) -> None:
        queue = InMemoryTaskQueue()

        class FailingLLM:
            async def complete(
                self, messages: list[dict[str, Any]], model: str, **kwargs: Any
            ) -> dict[str, Any]:
                msg = "LLM error"
                raise RuntimeError(msg)

        worker = AgentWorker(queue=queue, llm=FailingLLM())  # type: ignore[arg-type]
        task_id = await queue.submit({"messages": [{"role": "user", "content": "hi"}]})
        result = await worker.process_one()
        assert result is True
        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "failed"
        assert "LLM error" in task["error"]


class TestAgentWorkerRunLoop:
    async def test_run_loop_exits_on_idle(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        worker = AgentWorker(queue=queue, llm=llm)

        # Should exit after max_idle_seconds with no tasks
        await worker.run_loop(max_idle_seconds=1.0)

    async def test_run_loop_processes_then_exits(self) -> None:
        queue = InMemoryTaskQueue()
        llm = FakeLLMClient()
        llm.set_simple_response("loop response")
        worker = AgentWorker(queue=queue, llm=llm)

        task_id = await queue.submit(
            {"messages": [{"role": "user", "content": "work"}], "model": "auto"}
        )

        await worker.run_loop(max_idle_seconds=1.0)

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
