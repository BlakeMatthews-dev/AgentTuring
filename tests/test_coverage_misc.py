"""Targeted tests to increase coverage on miscellaneous modules.

Covers edge cases in: multi_intent, config loader, events (reactor),
prompt routes, skill forge, skill loader, quota billing, router filter,
tool executor, session store, prompt store, noop tracing, and protocols.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stronghold.types.config import TaskTypeConfig


# ── 1. Multi-intent edge cases (lines 52-58) ──────────────────────


class TestMultiIntentConfigKeywordFallback:
    """Cover the config-keyword fallback path in detect_multi_intent (lines 51-58)."""

    def test_config_keywords_fallback_detects_two_intents(self) -> None:
        """When strong indicators don't match, config keywords should classify parts."""
        from stronghold.classifier.multi_intent import detect_multi_intent

        task_types = {
            "weather": TaskTypeConfig(keywords=["forecast", "temperature"]),
            "cooking": TaskTypeConfig(keywords=["recipe", "bake"]),
        }
        # Neither "forecast" nor "recipe" are in STRONG_INDICATORS,
        # so the code falls through to the config keyword loop (lines 51-58).
        result = detect_multi_intent(
            "check the forecast and also find a recipe for cake",
            task_types,
        )
        assert set(result) >= {"weather", "cooking"}

    def test_config_keywords_single_type_returns_empty(self) -> None:
        """Config keywords that all resolve to the same type should return empty."""
        from stronghold.classifier.multi_intent import detect_multi_intent

        task_types = {
            "weather": TaskTypeConfig(keywords=["forecast", "temperature", "rain"]),
        }
        result = detect_multi_intent(
            "check the forecast and also check the temperature",
            task_types,
        )
        # Both parts classify as "weather" -> only 1 unique type -> empty
        assert result == []

    def test_config_keyword_break_after_first_match(self) -> None:
        """Once a config keyword matches a part, the inner break fires (line 57-58)."""
        from stronghold.classifier.multi_intent import detect_multi_intent

        task_types = {
            "alpha": TaskTypeConfig(keywords=["alphaword"]),
            "beta": TaskTypeConfig(keywords=["betaword"]),
            "gamma": TaskTypeConfig(keywords=["gammaword"]),
        }
        result = detect_multi_intent(
            "I need alphaword stuff and also betaword things",
            task_types,
        )
        assert len(result) >= 2
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" not in result


# ── 2. Config loader edge case (line 58 = jwks_url) ───────────────


class TestConfigLoaderJwksUrl:
    """Cover the STRONGHOLD_JWKS_URL env override (line 57-58)."""

    def test_jwks_url_env_override(self) -> None:
        from stronghold.config.loader import load_config

        os.environ["STRONGHOLD_JWKS_URL"] = "https://login.example.com/.well-known/jwks.json"
        try:
            config = load_config("/nonexistent/path.yaml")
            assert config.auth.jwks_url == "https://login.example.com/.well-known/jwks.json"
        finally:
            del os.environ["STRONGHOLD_JWKS_URL"]

    def test_invalid_yaml_raises_valueerror(self) -> None:
        from stronghold.config.loader import load_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(":\n  invalid:\n  - [\n")
            f.flush()
            try:
                with pytest.raises(ValueError, match="Invalid YAML"):
                    load_config(f.name)
            finally:
                os.unlink(f.name)


# ── 3. Reactor / events.py edge cases (line 280 = disable_trigger False) ──


class TestReactorDisableTriggerNotFound:
    """Cover disable_trigger returning False for unknown name (line 280)."""

    def test_disable_nonexistent_returns_false(self) -> None:
        from stronghold.events import Reactor

        reactor = Reactor(tick_hz=100)
        assert reactor.disable_trigger("nonexistent") is False

    def test_enable_nonexistent_returns_false(self) -> None:
        from stronghold.events import Reactor

        reactor = Reactor(tick_hz=100)
        assert reactor.enable_trigger("nonexistent") is False


class TestReactorBlockingFailure:
    """Cover _resolve_blocking exception path (lines 231-233)."""

    async def test_blocking_action_exception_propagates(self) -> None:
        from stronghold.events import Reactor
        from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

        class FailingBlockingAction:
            async def __call__(self, event: Event) -> dict[str, Any]:
                raise RuntimeError("blocking fail")

        reactor = Reactor(tick_hz=500)
        reactor.register(
            TriggerSpec(
                name="fail_gate",
                mode=TriggerMode.EVENT,
                event_pattern="gate_event",
                blocking=True,
            ),
            FailingBlockingAction(),
        )

        reactor_task = asyncio.create_task(reactor.start())
        with pytest.raises(RuntimeError, match="blocking fail"):
            await reactor.emit_and_wait(Event("gate_event"))

        reactor.stop()
        await reactor_task


class TestReactorStateTrigger:
    """Cover the STATE mode branch in _evaluate (lines 210-214)."""

    async def test_state_trigger_fires(self) -> None:
        from stronghold.events import Reactor
        from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

        class RecordAction:
            def __init__(self) -> None:
                self.calls: list[Event] = []

            async def __call__(self, event: Event) -> dict[str, Any]:
                self.calls.append(event)
                return {"ok": True}

        reactor = Reactor(tick_hz=500)
        action = RecordAction()

        reactor.register(
            TriggerSpec(
                name="state_check",
                mode=TriggerMode.STATE,
                interval_secs=0.001,  # Very short so it fires quickly
            ),
            action,
        )

        async def _stop_after() -> None:
            for _ in range(30):
                await asyncio.sleep(0.002)
            reactor.stop()

        stop_task = asyncio.create_task(_stop_after())
        await reactor.start()
        await stop_task

        # Should have fired at least once
        assert len(action.calls) >= 1
        assert action.calls[0].name.startswith("_state:")


class TestReactorTimeTrigger:
    """Cover the TIME mode branch (lines 203-207)."""

    async def test_time_trigger_no_match(self) -> None:
        """A TIME trigger with a time that doesn't match should not fire."""
        from stronghold.events import Reactor
        from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

        class RecordAction:
            def __init__(self) -> None:
                self.calls: list[Event] = []

            async def __call__(self, event: Event) -> dict[str, Any]:
                self.calls.append(event)
                return {"ok": True}

        reactor = Reactor(tick_hz=500)
        action = RecordAction()

        reactor.register(
            TriggerSpec(
                name="time_check",
                mode=TriggerMode.TIME,
                at_time="99:99",  # Will never match
            ),
            action,
        )

        async def _stop_after() -> None:
            for _ in range(10):
                await asyncio.sleep(0.002)
            reactor.stop()

        stop_task = asyncio.create_task(_stop_after())
        await reactor.start()
        await stop_task

        assert len(action.calls) == 0


class TestReactorIntervalJitter:
    """Cover interval jitter path (lines 197-198)."""

    async def test_interval_with_jitter(self) -> None:
        from stronghold.events import Reactor
        from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

        class RecordAction:
            def __init__(self) -> None:
                self.calls: list[Event] = []

            async def __call__(self, event: Event) -> dict[str, Any]:
                self.calls.append(event)
                return {"ok": True}

        reactor = Reactor(tick_hz=500)
        action = RecordAction()

        reactor.register(
            TriggerSpec(
                name="jittery",
                mode=TriggerMode.INTERVAL,
                interval_secs=0.01,
                jitter=0.5,  # +-50% jitter
            ),
            action,
        )

        async def _stop_after() -> None:
            for _ in range(50):
                await asyncio.sleep(0.002)
            reactor.stop()

        stop_task = asyncio.create_task(_stop_after())
        await reactor.start()
        await stop_task

        # Should still fire (first fire immediate, subsequent with jittered interval)
        assert len(action.calls) >= 1


class TestReactorNoEventPattern:
    """Cover event_pattern=None returning None (lines 188-189)."""

    async def test_event_trigger_without_pattern_does_not_fire(self) -> None:
        from stronghold.events import Reactor
        from stronghold.types.reactor import Event, TriggerMode, TriggerSpec

        class RecordAction:
            def __init__(self) -> None:
                self.calls: list[Event] = []

            async def __call__(self, event: Event) -> dict[str, Any]:
                self.calls.append(event)
                return {"ok": True}

        reactor = Reactor(tick_hz=500)
        action = RecordAction()

        # EVENT mode but no event_pattern -> _compiled_pattern will be None
        reactor.register(
            TriggerSpec(name="no_pattern", mode=TriggerMode.EVENT, event_pattern=""),
            action,
        )

        reactor.emit(Event("some_event"))

        async def _stop_after() -> None:
            for _ in range(10):
                await asyncio.sleep(0.002)
            reactor.stop()

        stop_task = asyncio.create_task(_stop_after())
        await reactor.start()
        await stop_task

        assert len(action.calls) == 0


# ── 4. Prompt routes edge cases (lines 342-363 = reject endpoint) ──


class TestPromptRouteReject:
    """Cover the reject_prompt route (lines 336-371)."""

    @pytest.fixture()
    def app_with_prompts(self) -> Any:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from stronghold.prompts.routes import _approvals, router
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.types.auth import AuthContext
        from tests.fakes import FakeAuthProvider

        app = FastAPI()
        app.include_router(router)

        pm = InMemoryPromptManager()
        admin_auth = AuthContext(
            user_id="admin-user",
            roles=frozenset({"admin"}),
            org_id="org1",
        )

        class _MinimalContainer:
            """Minimal container with only the fields prompt routes need."""
            prompt_manager = pm
            auth_provider = FakeAuthProvider(auth_context=admin_auth)

        app.state.container = _MinimalContainer()

        # Clear approvals between tests
        _approvals.clear()

        return TestClient(app), pm, _approvals

    def test_reject_prompt_version(self, app_with_prompts: Any) -> None:
        from stronghold.types.prompt import ApprovalRequest

        client, pm, approvals = app_with_prompts

        # Set up a prompt with versions
        pm._versions["test/prompt"] = {1: ("content v1", {}), 2: ("content v2", {})}
        pm._labels["test/prompt"] = {"production": 1, "latest": 2}

        # Create a pending approval
        approval = ApprovalRequest(
            prompt_name="test/prompt",
            version=2,
            requested_by="user1",
        )
        approvals["test/prompt"] = [approval]

        resp = client.post(
            "/v1/stronghold/prompts/test/prompt/reject",
            json={"version": 2, "reason": "Does not meet compliance"},
            headers={"authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["reason"] == "Does not meet compliance"
        assert data["reviewed_by"] == "admin-user"

    def test_reject_nonexistent_approval_404(self, app_with_prompts: Any) -> None:
        client, pm, approvals = app_with_prompts

        resp = client.post(
            "/v1/stronghold/prompts/test/prompt/reject",
            json={"version": 99},
            headers={"authorization": "Bearer test-token"},
        )
        assert resp.status_code == 404
        assert "detail" in resp.json()
        assert "approval" in resp.json()["detail"].lower()

    def test_approve_nonexistent_approval_404(self, app_with_prompts: Any) -> None:
        client, pm, approvals = app_with_prompts

        resp = client.post(
            "/v1/stronghold/prompts/test/prompt/approve",
            json={"version": 99},
            headers={"authorization": "Bearer test-token"},
        )
        assert resp.status_code == 404
        assert "detail" in resp.json()
        assert "approval" in resp.json()["detail"].lower()


# ── 5. Skill forge LLM path (lines 286-288 = _call_llm exception) ──


class TestSkillForgeLLMFailure:
    """Cover _call_llm exception handling (lines 286-288)."""

    async def test_call_llm_exception_returns_none(self, tmp_path: Path) -> None:
        from stronghold.skills.forge import LLMSkillForge

        class ExplodingLLM:
            async def complete(self, **kwargs: Any) -> dict[str, Any]:
                raise ConnectionError("LLM unreachable")

            async def stream(self, **kwargs: Any) -> Any:
                yield ""

        forge = LLMSkillForge(ExplodingLLM(), tmp_path)
        # forge._call_llm should catch the exception and return None
        result = await forge._call_llm("test prompt")
        assert result is None

    async def test_call_llm_no_choices_returns_none(self, tmp_path: Path) -> None:
        from stronghold.skills.forge import LLMSkillForge

        class EmptyChoicesLLM:
            async def complete(self, **kwargs: Any) -> dict[str, Any]:
                return {"choices": []}

            async def stream(self, **kwargs: Any) -> Any:
                yield ""

        forge = LLMSkillForge(EmptyChoicesLLM(), tmp_path)
        result = await forge._call_llm("test prompt")
        # No choices -> if block skipped -> returns None
        assert result is None

    async def test_forge_with_llm_failure_raises(self, tmp_path: Path) -> None:
        from stronghold.skills.forge import LLMSkillForge

        class ExplodingLLM:
            async def complete(self, **kwargs: Any) -> dict[str, Any]:
                raise ConnectionError("LLM unreachable")

            async def stream(self, **kwargs: Any) -> Any:
                yield ""

        forge = LLMSkillForge(ExplodingLLM(), tmp_path)
        # _call_llm returns None -> forge raises "empty response"
        with pytest.raises(ValueError, match="empty response"):
            await forge.forge("make a tool")

    async def test_mutate_with_llm_failure_returns_error(self, tmp_path: Path) -> None:
        from stronghold.skills.forge import LLMSkillForge
        from stronghold.types.memory import Learning

        class ExplodingLLM:
            async def complete(self, **kwargs: Any) -> dict[str, Any]:
                raise ConnectionError("LLM unreachable")

            async def stream(self, **kwargs: Any) -> Any:
                yield ""

        # Write skill file
        skill_content = """---
name: test_skill
description: A test.
groups: [general]
parameters:
  type: object
  properties: {}
endpoint: ""
---

Test instructions.
"""
        (tmp_path / "test_skill.md").write_text(skill_content)

        forge = LLMSkillForge(ExplodingLLM(), tmp_path)
        learning = Learning(learning="improve this", tool_name="test_skill")
        result = await forge.mutate("test_skill", learning)
        assert result["status"] == "error"
        assert "empty response" in result["error"].lower()


# ── 6. Skill loader edge cases (lines 61-62 = community parse fail) ──


class TestSkillLoaderCommunityEdgeCases:
    """Cover community directory loading with invalid files (lines 61-62)."""

    def test_community_invalid_file_skipped(self, tmp_path: Path) -> None:
        from stronghold.skills.loader import FilesystemSkillLoader

        community = tmp_path / "community"
        community.mkdir()
        (community / "bad.md").write_text("not a valid skill file")

        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        # Invalid file in community/ should be silently skipped (skill is None, line 64)
        assert len(skills) == 0

    def test_community_unreadable_file_skipped(self, tmp_path: Path) -> None:
        from stronghold.skills.loader import FilesystemSkillLoader

        community = tmp_path / "community"
        community.mkdir()
        bad_file = community / "unreadable.md"
        bad_file.write_text("content")
        bad_file.chmod(0o000)

        loader = FilesystemSkillLoader(tmp_path)
        try:
            skills = loader.load_all()
            # OSError caught at line 62 — unreadable file skipped, returns empty list
            assert skills == []
        finally:
            bad_file.chmod(0o644)

    def test_symlink_in_skills_dir_skipped(self, tmp_path: Path) -> None:
        """Cover the symlink skip path (lines 38-39)."""
        from stronghold.skills.loader import FilesystemSkillLoader

        valid_content = """---
name: real_tool
description: A real tool.
groups: [general]
parameters:
  type: object
  properties: {}
endpoint: ""
---

Instructions.
"""
        (tmp_path / "real.md").write_text(valid_content)
        symlink_path = tmp_path / "linked.md"
        symlink_path.symlink_to(tmp_path / "real.md")

        loader = FilesystemSkillLoader(tmp_path)
        skills = loader.load_all()
        # Only real.md loaded, symlink skipped
        names = [s.name for s in skills]
        assert "real_tool" in names
        # The symlink should have been skipped
        assert len([s for s in skills if s.name == "real_tool"]) == 1


# ── 7. Quota billing edge cases (lines 18-20) ─────────────────────


class TestBillingCycleKey:
    """Cover cycle_key and daily_budget functions."""

    def test_cycle_key_daily(self) -> None:
        from stronghold.quota.billing import cycle_key

        key = cycle_key("daily")
        # Should be YYYY-MM-DD format
        assert len(key) == 10
        assert key.count("-") == 2

    def test_cycle_key_monthly(self) -> None:
        from stronghold.quota.billing import cycle_key

        key = cycle_key("monthly")
        # Should be YYYY-MM format
        assert len(key) == 7
        assert key.count("-") == 1

    def test_daily_budget_daily_cycle(self) -> None:
        from stronghold.quota.billing import daily_budget

        result = daily_budget(1000, "daily")
        assert result == 1000.0

    def test_daily_budget_monthly_cycle(self) -> None:
        from stronghold.quota.billing import daily_budget

        result = daily_budget(30000, "monthly")
        assert result == 1000.0  # 30000 / 30


# ── 8. Router filter edge case (line 72 = over 100% no paygo) ──


class TestRouterFilterPaygoEdge:
    """Cover the hard block at 100% usage without pay-as-you-go (line 71-72)."""

    def test_over_100_pct_no_paygo_blocked(self) -> None:
        from stronghold.router.filter import filter_candidates
        from stronghold.types.intent import Intent
        from stronghold.types.model import ModelConfig, ProviderConfig

        intent = Intent(task_type="chat", min_tier="small")
        models = {
            "m1": ModelConfig(provider="p1", tier="small", quality=0.5),
        }
        providers = {
            "p1": ProviderConfig(
                status="active",
                overage_cost_per_1k_input=0.0,
                overage_cost_per_1k_output=0.0,
            ),
        }

        result = filter_candidates(
            intent, models, providers, usage_pcts={"p1": 1.05}
        )
        assert len(result) == 0

    def test_over_100_pct_with_paygo_allowed(self) -> None:
        from stronghold.router.filter import filter_candidates
        from stronghold.types.intent import Intent
        from stronghold.types.model import ModelConfig, ProviderConfig

        intent = Intent(task_type="chat", min_tier="small")
        models = {
            "m1": ModelConfig(provider="p1", tier="small", quality=0.5),
        }
        providers = {
            "p1": ProviderConfig(
                status="active",
                overage_cost_per_1k_input=0.01,
                overage_cost_per_1k_output=0.02,
            ),
        }

        result = filter_candidates(
            intent, models, providers, usage_pcts={"p1": 1.05}
        )
        assert len(result) == 1

    def test_reserve_zone_non_critical_no_paygo_blocked(self) -> None:
        """Cover line 75-76: reserve enforcement blocks non-critical without paygo."""
        from stronghold.router.filter import filter_candidates
        from stronghold.types.intent import Intent
        from stronghold.types.model import ModelConfig, ProviderConfig

        intent = Intent(task_type="chat", min_tier="small", tier="P2")
        models = {
            "m1": ModelConfig(provider="p1", tier="small", quality=0.5),
        }
        providers = {
            "p1": ProviderConfig(
                status="active",
                overage_cost_per_1k_input=0.0,
                overage_cost_per_1k_output=0.0,
            ),
        }

        # usage_pct = 0.96 >= (1.0 - 0.05), tier != P0, no paygo
        result = filter_candidates(
            intent, models, providers, usage_pcts={"p1": 0.96}
        )
        assert len(result) == 0

    def test_reserve_zone_critical_priority_allowed(self) -> None:
        """Critical priority bypasses reserve enforcement."""
        from stronghold.router.filter import filter_candidates
        from stronghold.types.intent import Intent
        from stronghold.types.model import ModelConfig, ProviderConfig

        intent = Intent(task_type="chat", min_tier="small", tier="P0")
        models = {
            "m1": ModelConfig(provider="p1", tier="small", quality=0.5),
        }
        providers = {
            "p1": ProviderConfig(
                status="active",
                overage_cost_per_1k_input=0.0,
                overage_cost_per_1k_output=0.0,
            ),
        }

        result = filter_candidates(
            intent, models, providers, usage_pcts={"p1": 0.96}
        )
        assert len(result) == 1

    def test_max_tier_filtering(self) -> None:
        """Cover the max_tier filter path (line 58)."""
        from stronghold.router.filter import filter_candidates
        from stronghold.types.intent import Intent
        from stronghold.types.model import ModelConfig, ProviderConfig

        intent = Intent(task_type="chat", min_tier="small", max_tier="medium")
        models = {
            "small_model": ModelConfig(provider="p1", tier="small", quality=0.3),
            "large_model": ModelConfig(provider="p1", tier="large", quality=0.9),
        }
        providers = {"p1": ProviderConfig(status="active")}

        result = filter_candidates(intent, models, providers)
        # large model should be filtered out (tier large > max_tier medium)
        model_ids = [r[0] for r in result]
        assert "small_model" in model_ids
        assert "large_model" not in model_ids


# ── 9. Tool executor edge cases (lines 113-116) ───────────────────


class TestToolDispatcherEdgeCases:
    """Cover timeout and exception paths in ToolDispatcher."""

    async def test_tool_timeout(self) -> None:
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry
        from stronghold.types.tool import ToolDefinition, ToolResult

        registry = InMemoryToolRegistry()

        async def slow_executor(args: dict[str, Any]) -> ToolResult:
            await asyncio.sleep(10)
            return ToolResult(content="done")

        defn = ToolDefinition(name="slow_tool", description="Slow tool")
        registry.register(defn, slow_executor)

        dispatcher = ToolDispatcher(registry, default_timeout=0.01)
        result = await dispatcher.execute("slow_tool", {})
        assert "timed out" in result

    async def test_tool_exception(self) -> None:
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry
        from stronghold.types.tool import ToolDefinition, ToolResult

        registry = InMemoryToolRegistry()

        async def failing_executor(args: dict[str, Any]) -> ToolResult:
            raise RuntimeError("executor crashed")

        defn = ToolDefinition(name="bad_tool", description="Bad tool")
        registry.register(defn, failing_executor)

        dispatcher = ToolDispatcher(registry, default_timeout=5.0)
        result = await dispatcher.execute("bad_tool", {})
        assert "failed" in result
        assert "executor crashed" in result

    async def test_tool_not_found(self) -> None:
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry

        registry = InMemoryToolRegistry()
        dispatcher = ToolDispatcher(registry)
        result = await dispatcher.execute("nonexistent", {})
        assert "not registered" in result

    async def test_tool_with_endpoint_ssrf_blocked(self) -> None:
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry
        from stronghold.types.tool import ToolDefinition

        registry = InMemoryToolRegistry()
        defn = ToolDefinition(
            name="internal_tool",
            description="Tool with internal endpoint",
            endpoint="http://169.254.169.254/latest/meta-data/",
        )
        registry.register(defn)

        dispatcher = ToolDispatcher(registry)
        result = await dispatcher.execute("internal_tool", {})
        assert "blocked" in result.lower()

    async def test_tool_with_non_https_endpoint(self) -> None:
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry
        from stronghold.types.tool import ToolDefinition

        registry = InMemoryToolRegistry()
        defn = ToolDefinition(
            name="http_tool",
            description="Tool with http endpoint",
            endpoint="http://example.com/api",
        )
        registry.register(defn)

        dispatcher = ToolDispatcher(registry)
        result = await dispatcher.execute("http_tool", {})
        assert "HTTPS" in result

    async def test_tool_error_result(self) -> None:
        """Cover the result.success=False path (line 58)."""
        from stronghold.tools.executor import ToolDispatcher
        from stronghold.tools.registry import InMemoryToolRegistry
        from stronghold.types.tool import ToolDefinition, ToolResult

        registry = InMemoryToolRegistry()

        async def error_executor(args: dict[str, Any]) -> ToolResult:
            return ToolResult(content="", success=False, error="something went wrong")

        defn = ToolDefinition(name="err_tool", description="Error tool")
        registry.register(defn, error_executor)

        dispatcher = ToolDispatcher(registry, default_timeout=5.0)
        result = await dispatcher.execute("err_tool", {})
        assert "Error: something went wrong" in result


# ── 10. Session store validation edge cases (lines 71-74) ─────────


class TestSessionValidation:
    """Cover validate_and_build_session_id edge cases."""

    def test_none_returns_none(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        result = validate_and_build_session_id(None, "org1")
        assert result is None

    def test_invalid_format_raises(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        with pytest.raises(ValueError, match="Invalid session ID format"):
            validate_and_build_session_id("bad session id!", "org1")

    def test_already_scoped_valid(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        result = validate_and_build_session_id("org1/team1/user1:chat", "org1")
        assert result == "org1/team1/user1:chat"

    def test_already_scoped_wrong_org_raises(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        with pytest.raises(ValueError, match="does not belong"):
            validate_and_build_session_id("org2/team/user:chat", "org1")

    def test_bare_name_auto_scoped(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        result = validate_and_build_session_id("my-session", "org1", "team1", "user1")
        assert result == "org1/team1/user1:my-session"

    def test_bare_name_defaults_underscores(self) -> None:
        from stronghold.sessions.store import validate_and_build_session_id

        result = validate_and_build_session_id("my-session", "org1")
        assert result == "org1/_/_:my-session"


class TestSessionOwnership:
    """Cover validate_session_ownership edge cases."""

    def test_empty_org_id_returns_false(self) -> None:
        from stronghold.sessions.store import validate_session_ownership

        assert validate_session_ownership("org1/team/user:chat", "") is False

    def test_matching_org_returns_true(self) -> None:
        from stronghold.sessions.store import validate_session_ownership

        assert validate_session_ownership("org1/team/user:chat", "org1") is True

    def test_wrong_org_returns_false(self) -> None:
        from stronghold.sessions.store import validate_session_ownership

        assert validate_session_ownership("org2/team/user:chat", "org1") is False


class TestBuildSessionId:
    """Cover build_session_id."""

    def test_builds_correct_format(self) -> None:
        from stronghold.sessions.store import build_session_id

        result = build_session_id("org1", "team1", "user1", "chat")
        assert result == "org1/team1/user1:chat"


# ── 11. Prompt store edge case (line 45 = version not in versions) ──


class TestPromptStoreVersionNotFound:
    """Cover the case where a label points to a nonexistent version (line 44-45)."""

    async def test_label_points_to_missing_version(self) -> None:
        from stronghold.prompts.store import InMemoryPromptManager

        pm = InMemoryPromptManager()
        await pm.upsert("prompt1", "content v1")

        # Manually set a label to point to a nonexistent version
        pm._labels["prompt1"]["broken"] = 999

        content, config = await pm.get_with_config("prompt1", label="broken")
        # version 999 doesn't exist, so entry is None -> returns ("", {})
        assert content == ""
        assert config == {}


# ── 12. Noop tracing (line 51 = NoopTrace.score) ──────────────────


class TestNoopTracingComplete:
    """Cover all NoopTrace/NoopSpan methods for full coverage."""

    def test_noop_trace_score(self) -> None:
        from stronghold.tracing.noop import NoopTrace

        trace = NoopTrace()
        # score is a no-op that should not raise (line 50-51)
        trace.score("quality", 0.95, comment="great")
        trace.score("latency", 0.5)

    def test_noop_trace_update(self) -> None:
        from stronghold.tracing.noop import NoopTrace

        trace = NoopTrace()
        trace.update({"key": "value"})

    def test_noop_trace_end(self) -> None:
        from stronghold.tracing.noop import NoopTrace

        trace = NoopTrace()
        trace.end()

    def test_noop_trace_id(self) -> None:
        from stronghold.tracing.noop import NoopTrace

        trace = NoopTrace()
        assert trace.trace_id == "noop-trace"

    def test_noop_span_context_manager(self) -> None:
        from stronghold.tracing.noop import NoopSpan

        span = NoopSpan()
        with span as s:
            s.set_input({"data": "test"})
            s.set_output({"result": "ok"})
            s.set_usage(input_tokens=10, output_tokens=20, model="test")
        # __exit__ returns None, no exception

    def test_noop_tracing_backend_create_trace(self) -> None:
        from stronghold.tracing.noop import NoopTracingBackend

        backend = NoopTracingBackend()
        trace = backend.create_trace(
            user_id="user1",
            session_id="session1",
            name="test-trace",
            metadata={"key": "val"},
        )
        assert trace.trace_id == "noop-trace"
        span = trace.span("test-span")
        assert span is not None


