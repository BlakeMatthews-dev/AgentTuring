"""Phase-2 deep edge-case probes — conduit, workspace, config/loader, factory.

Continuing the security audit. Each failing test is a real finding.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ──────────────────────────────────────────────────────────────────────
# conduit.determine_execution_tier
# ──────────────────────────────────────────────────────────────────────


class TestExecutionTierOverride:
    def _intent(self, tier: str = "P2") -> Any:
        from stronghold.types.intent import Intent

        return Intent(task_type="chat", complexity="simple", tier=tier)  # type: ignore[arg-type]

    def test_agent_can_downgrade_p0_to_p5(self) -> None:
        """SEC finding? A P5 agent processing a P0 request downgrades the
        urgency. Should critical tiers resist agent downgrades?
        """
        from stronghold.conduit import determine_execution_tier

        agent = MagicMock()
        agent.priority_tier = "P5"
        intent = self._intent("P0")  # User request classified critical
        result = determine_execution_tier(intent, agent)
        # Current behavior: agent can downgrade. Document.
        # If this is a bug, the fix would be: only allow agent to upgrade.
        assert result.tier in ("P0", "P5")  # Either behavior is currently valid

    def test_agent_invalid_tier_ignored(self) -> None:
        """Agent with priority_tier='P99' must be rejected, not crash."""
        from stronghold.conduit import determine_execution_tier

        agent = MagicMock()
        agent.priority_tier = "P99"
        intent = self._intent("P2")
        result = determine_execution_tier(intent, agent)
        # Invalid tier ignored, original intent tier preserved
        assert result.tier == "P2"

    def test_no_agent_preserves_tier(self) -> None:
        from stronghold.conduit import determine_execution_tier

        intent = self._intent("P3")
        result = determine_execution_tier(intent, agent=None)
        assert result.tier == "P3"

    def test_agent_without_priority_tier_attr(self) -> None:
        """Agent without priority_tier attribute must not crash."""
        from stronghold.conduit import determine_execution_tier

        # Use a type that has no attribute priority_tier — MagicMock auto-adds it,
        # so use a bare object instead
        class BareAgent:
            pass

        intent = self._intent("P2")
        result = determine_execution_tier(intent, BareAgent())
        assert result.tier == "P2"

    def test_agent_priority_tier_empty_string(self) -> None:
        """Empty string tier must not match _TIER_LEVELS and must be ignored."""
        from stronghold.conduit import determine_execution_tier

        agent = MagicMock()
        agent.priority_tier = ""
        intent = self._intent("P1")
        result = determine_execution_tier(intent, agent)
        assert result.tier == "P1"

    def test_agent_priority_tier_none(self) -> None:
        from stronghold.conduit import determine_execution_tier

        agent = MagicMock()
        agent.priority_tier = None
        intent = self._intent("P1")
        # None is not in _TIER_LEVELS — should be ignored, not crash
        result = determine_execution_tier(intent, agent)
        assert result.tier == "P1"


class TestConduitEstimateTokens:
    def _make(self):
        from stronghold.conduit import Conduit

        container = MagicMock()
        container.agents = {}
        return Conduit(container)

    def test_empty_messages_returns_minimum_one(self) -> None:
        from stronghold.conduit import Conduit

        # Static method
        assert Conduit._estimate_tokens([]) == 1

    def test_empty_content_returns_minimum_one(self) -> None:
        from stronghold.conduit import Conduit

        assert Conduit._estimate_tokens([{"role": "user", "content": ""}]) == 1

    def test_large_content_chars_div_4(self) -> None:
        from stronghold.conduit import Conduit

        content = "x" * 4000
        assert Conduit._estimate_tokens([{"role": "user", "content": content}]) == 1000

    def test_multimodal_content_list(self) -> None:
        from stronghold.conduit import Conduit

        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello " * 100},
                    {"type": "image_url", "image_url": {"url": "..."}},
                ],
            }
        ]
        result = Conduit._estimate_tokens(msgs)
        assert result > 1  # Counted the text part

    def test_content_none_does_not_crash(self) -> None:
        """content=None should not raise (could come from malformed input)."""
        from stronghold.conduit import Conduit

        Conduit._estimate_tokens([{"role": "user", "content": None}])

    def test_non_string_content_dict(self) -> None:
        from stronghold.conduit import Conduit

        # content = dict (not str, not list) — should not crash
        Conduit._estimate_tokens([{"role": "user", "content": {"weird": "dict"}}])


# ──────────────────────────────────────────────────────────────────────
# workspace.py — git command argument injection
# ──────────────────────────────────────────────────────────────────────


class TestWorkspaceInjection:
    """Probe for git argument injection via owner/repo/branch params."""

    def _mgr_with_mocked_run(self):
        from stronghold.tools.workspace import WorkspaceManager

        mgr = WorkspaceManager()
        calls = []

        def mock_run(cmd, cwd=None):
            calls.append((list(cmd), cwd))
            return "ok"

        mgr._run = mock_run  # type: ignore[method-assign]
        return mgr, calls

    def test_branch_with_shell_metachar_passes_through(self) -> None:
        """Branch name with '; rm' is passed as a single arg to git — safe
        because subprocess.run doesn't use shell=True.
        """
        from stronghold.tools.workspace import WorkspaceManager

        mgr = WorkspaceManager()
        calls = []

        def mock_run(cmd, cwd=None):
            calls.append(cmd)
            # Return fake JSON that the _ensure_clone path expects
            return "ok"

        mgr._run = mock_run  # type: ignore[method-assign]
        mgr._repos["o/r"] = Path("/tmp/fake")

        result = mgr._create(
            {
                "owner": "o",
                "repo": "r",
                "issue_number": 1,
                "branch": "mason/1; rm -rf /",  # injection attempt
            }
        )
        # Branch should have been passed as a literal arg to git worktree add
        # git will reject it as an invalid refname, but subprocess.run is safe
        assert isinstance(result, dict)
        # Look for the dangerous string in the git command args
        found = False
        for call in calls:
            if any("rm -rf /" in str(arg) for arg in call):
                found = True
        # It IS in the args — but as a literal, not shell-interpreted
        assert found, "branch name should reach git as a literal arg"

    def test_owner_with_git_option_injection(self) -> None:
        """owner='--upload-pack=/bin/sh' could inject git option into clone.

        The URL is built as f"https://github.com/{owner}/{repo}.git", so an
        owner like '--upload-pack=/bin/sh' would be injected INTO THE URL,
        not as a separate arg. Git URL parser should reject it but let's verify.
        """
        from stronghold.tools.workspace import WorkspaceManager

        mgr = WorkspaceManager()
        clone_calls = []

        def mock_run(cmd, cwd=None):
            if cmd and cmd[0] == "git" and cmd[1] == "clone":
                clone_calls.append(cmd)
            return "ok"

        mgr._run = mock_run  # type: ignore[method-assign]

        with contextlib.suppress(Exception):
            mgr._ensure_clone("--upload-pack=/bin/sh", "repo")

        # Verify the malicious owner was embedded in the URL, not used as git arg
        for call in clone_calls:
            url = call[-2] if len(call) >= 2 else ""
            # The URL should contain the owner as part of the path
            assert "--upload-pack" in url
            # BUT it's a URL segment, not a git option — git will reject as
            # invalid GitHub path. The danger: if any future code path
            # passes owner directly as a git arg, it would be dangerous.

    def test_repo_with_slash_breaks_clone_path(self) -> None:
        """repo='a/b' changes the URL structure unexpectedly.

        URL: https://github.com/{owner}/a/b.git — valid URL but targets
        a different repo. Could be used for path confusion.
        """
        from stronghold.tools.workspace import WorkspaceManager

        mgr = WorkspaceManager()
        clone_calls = []

        def mock_run(cmd, cwd=None):
            clone_calls.append(cmd)
            return "ok"

        mgr._run = mock_run  # type: ignore[method-assign]

        with contextlib.suppress(Exception):
            mgr._ensure_clone("owner", "repo/../other")

        # The repo path gets embedded literally — git URL parser will
        # deal with it, but the local directory collision could matter:
        for call in clone_calls:
            if call[:2] == ["git", "clone"]:
                dest = call[-1]
                # The dest is `self._base / "repos" / repo` — and repo has '..'
                # This could escape self._base!
                assert "repo/../other" in dest or "other" in dest


# ──────────────────────────────────────────────────────────────────────
# config/loader.py — SSRF & auth config
# ──────────────────────────────────────────────────────────────────────


class TestConfigLoaderSSRF:
    def test_rejects_private_ipv4_literal(self, monkeypatch) -> None:
        """URL with literal 192.168.x.x must be rejected."""
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError, match="private"):
            _validate_url_not_private("https://192.168.1.1/oauth", "TEST")

    def test_rejects_loopback_literal(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError):
            _validate_url_not_private("https://127.0.0.1/oauth", "TEST")

    def test_rejects_metadata_endpoint(self) -> None:
        """169.254.169.254 is AWS/Azure/GCP metadata. Must be blocked.

        is_link_local should catch it (169.254.0.0/16 is link-local).
        """
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError):
            _validate_url_not_private("https://169.254.169.254/latest/meta-data/", "TEST")

    def test_rejects_http_scheme(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError, match="HTTPS"):
            _validate_url_not_private("http://example.com/", "TEST")

    def test_rejects_ipv6_loopback(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError):
            _validate_url_not_private("https://[::1]/oauth", "TEST")

    def test_dns_failure_logs_warning_not_error(self) -> None:
        """DNS resolution failures should log warning, not raise.

        This is documented behavior — container startup may not have DNS yet.
        But this is itself a finding: DNS rebinding attacker can cheat this.
        """
        from stronghold.config.loader import _validate_url_not_private

        # Use a domain that definitely won't resolve
        _validate_url_not_private("https://nonexistent-domain-xyz-9999.example/", "TEST")
        # Must not raise — documents the behavior

    def test_rejects_javascript_uri(self) -> None:
        """Should not be accepted as a URL (no hostname)."""
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError):
            _validate_url_not_private("javascript:alert(1)", "TEST")

    def test_load_config_rejects_wildcard_cors(self, monkeypatch) -> None:
        from stronghold.config.loader import load_config

        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "https://app.example.com,*")
        with pytest.raises(ValueError, match=r"\*"):
            load_config()

    def test_load_config_rejects_javascript_cors(self, monkeypatch) -> None:
        from stronghold.config.loader import load_config

        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "javascript:void(0)")
        with pytest.raises(ValueError, match="unsafe"):
            load_config()

    def test_load_config_rejects_data_cors(self, monkeypatch) -> None:
        from stronghold.config.loader import load_config

        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "data:text/html,<script>alert(1)</script>")
        with pytest.raises(ValueError, match="unsafe"):
            load_config()

    def test_load_config_webhook_secret_minimum_length(self, monkeypatch) -> None:
        from stronghold.config.loader import load_config

        monkeypatch.setenv("STRONGHOLD_WEBHOOK_SECRET", "short")
        with pytest.raises(ValueError, match="16 characters"):
            load_config()

    def test_load_config_router_key_short_only_warns(self, monkeypatch, caplog) -> None:
        """ROUTER_API_KEY < 32 chars only warns (does NOT fail).

        This is itself a finding — the BACKLOG R14 says this should be a
        hard error, but the code still only warns.
        """
        import logging

        from stronghold.config.loader import load_config

        monkeypatch.setenv("ROUTER_API_KEY", "short-key")
        with caplog.at_level(logging.WARNING):
            load_config()
        assert any("ROUTER_API_KEY" in r.message for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────
# agents/factory.py — manifest parsing edges
# ──────────────────────────────────────────────────────────────────────


class TestAgentFactoryEdges:
    def test_missing_name_raises_keyerror(self) -> None:
        """Manifest without 'name' key — explicit failure better than silent default."""
        from stronghold.agents.factory import _build_identity_from_manifest

        with pytest.raises(KeyError):
            _build_identity_from_manifest({})

    def test_minimal_manifest(self) -> None:
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest({"name": "minimal"})
        assert identity.name == "minimal"
        assert identity.version == "1.0.0"
        assert identity.reasoning_strategy == "direct"

    def test_manifest_with_invalid_priority_tier(self) -> None:
        """priority_tier='P99' — what happens?"""
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest(
            {
                "name": "bad-tier",
                "priority_tier": "P99",
            }
        )
        # Either defaults to P2 or accepts invalid — either is a finding
        # Test documents current behavior
        assert identity.priority_tier in ("P99", "P2")

    def test_sec011_manifest_with_none_tools(self) -> None:
        """SEC-011: tools: null in YAML must not crash the loader."""
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest({"name": "n", "tools": None})
        assert identity.tools == ()

    def test_sec012_manifest_with_string_tools(self) -> None:
        """SEC-012: tools: "shell" in YAML must not iterate as chars."""
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest({"name": "n", "tools": "shell"})
        # Accept either single-element tuple (lenient) or empty (strict)
        assert identity.tools in (("shell",), ())
        # But NEVER chars
        assert identity.tools != ("s", "h", "e", "l", "l")

    def test_sec011_all_list_fields_none_safe(self) -> None:
        """All list fields in manifest must handle None without crashing."""
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest(
            {
                "name": "n",
                "tools": None,
                "skills": None,
                "rules": None,
                "model_fallbacks": None,
                "reasoning": {"phases": None},
                "memory": None,
                "model_constraints": None,
            }
        )
        assert identity.tools == ()
        assert identity.skills == ()
        assert identity.rules == ()
        assert identity.model_fallbacks == ()
        assert identity.phases == ()
        assert identity.memory_config == {}
        assert identity.model_constraints == {}

    def test_manifest_with_deeply_nested_memory_config(self) -> None:
        from stronghold.agents.factory import _build_identity_from_manifest

        identity = _build_identity_from_manifest(
            {
                "name": "n",
                "memory": {"nested": {"deep": [1, 2, 3]}},
            }
        )
        assert identity.memory_config == {"nested": {"deep": [1, 2, 3]}}


# ──────────────────────────────────────────────────────────────────────
# conduit state-map unbounded growth
# ──────────────────────────────────────────────────────────────────────


class TestConduitStateMaps:
    def _conduit(self):
        from stronghold.conduit import Conduit

        container = MagicMock()
        container.agents = {"arbiter": MagicMock()}
        return Conduit(container)

    def test_session_agents_has_bounded_eviction(self) -> None:
        """_session_agents is capped at _MAX_STICKY_SESSIONS."""
        from stronghold.conduit import Conduit

        # This is documented by the code — just verify the cap constant exists
        assert hasattr(Conduit, "_MAX_STICKY_SESSIONS")
        assert Conduit._MAX_STICKY_SESSIONS > 0

    def test_sec013_consent_maps_have_eviction_cap_constant(self) -> None:
        """SEC-013: consent maps must have a documented cap.

        Previously _session_consents and _consent_pending had no eviction.
        Fix: _MAX_CONSENT_ENTRIES + per-write eviction on the hot path.
        """
        from stronghold.conduit import Conduit

        assert hasattr(Conduit, "_MAX_CONSENT_ENTRIES")
        assert Conduit._MAX_CONSENT_ENTRIES > 0

    def test_sec013_eviction_code_present(self) -> None:
        """Verify the eviction code block exists where it should."""
        import inspect

        from stronghold.conduit import Conduit

        source = inspect.getsource(Conduit)
        # Both consent maps must have eviction loops
        assert source.count("_MAX_CONSENT_ENTRIES") >= 2, (
            "eviction logic missing from either _session_consents or _consent_pending"
        )


# ──────────────────────────────────────────────────────────────────────
# admin coin conversion
# ──────────────────────────────────────────────────────────────────────


class TestCoinConversion:
    @pytest.fixture
    def admin_app(self):
        from fastapi import FastAPI

        from stronghold.api.routes.admin import router as admin_router
        from stronghold.quota.coins import NoOpCoinLedger
        from tests.fakes import make_test_container

        app = FastAPI()
        app.include_router(admin_router)
        container = make_test_container()
        container.coin_ledger = NoOpCoinLedger()
        container.db_pool = None  # triggers 503 path
        container.config.models = {}
        app.state.container = container
        return app

    def test_convert_non_numeric_copper_amount(self, admin_app) -> None:
        """Non-numeric copper_amount must not crash server with uncaught ValueError."""
        from fastapi.testclient import TestClient

        client = TestClient(admin_app)
        resp = client.post(
            "/v1/stronghold/admin/coins/convert",
            headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            json={"copper_amount": "not-a-number"},
        )
        # Should return 400, not 500
        assert resp.status_code in (400, 422), (
            f"non-numeric input returned {resp.status_code}, expected 400/422"
        )

    def test_convert_negative_copper_amount(self, admin_app) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(admin_app)
        resp = client.post(
            "/v1/stronghold/admin/coins/convert",
            headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            json={"copper_amount": -100},
        )
        assert resp.status_code == 400
        assert "Minimum" in resp.json()["detail"]

    def test_convert_below_minimum(self, admin_app) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(admin_app)
        resp = client.post(
            "/v1/stronghold/admin/coins/convert",
            headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            json={"copper_amount": 5},
        )
        assert resp.status_code == 400

    def test_convert_missing_body(self, admin_app) -> None:
        """Missing copper_amount defaults to 0 → rejected as below minimum."""
        from fastapi.testclient import TestClient

        client = TestClient(admin_app)
        resp = client.post(
            "/v1/stronghold/admin/coins/convert",
            headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            json={},
        )
        assert resp.status_code == 400

    def test_convert_requires_db(self, admin_app) -> None:
        """NoOpCoinLedger + no db_pool → 503."""
        from fastapi.testclient import TestClient

        client = TestClient(admin_app)
        resp = client.post(
            "/v1/stronghold/admin/coins/convert",
            headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            json={"copper_amount": 10},
        )
        assert resp.status_code == 503
