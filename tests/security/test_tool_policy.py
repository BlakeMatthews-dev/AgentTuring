"""Tests for the Tool Policy layer (ADR-K8S-019).

Tests both the CasbinToolPolicy (real Casbin enforcer) and the
FakeToolPolicy (in-memory test double).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from stronghold.security.tool_policy import (
    CasbinToolPolicy,
    ToolPolicyProtocol,
    create_tool_policy,
)
from tests.fakes import FakeToolPolicy


# ── FakeToolPolicy tests ────────────────────────────────────────────


class TestFakeToolPolicy:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(FakeToolPolicy(), ToolPolicyProtocol)

    def test_default_allows_tool_call(self) -> None:
        policy = FakeToolPolicy()
        assert policy.check_tool_call("alice", "acme", "shell_exec") is True

    def test_default_allows_task_creation(self) -> None:
        policy = FakeToolPolicy()
        assert policy.check_task_creation("alice", "acme", "ranger") is True

    def test_deny_tool_blocks(self) -> None:
        policy = FakeToolPolicy()
        policy.deny_tool("alice", "acme", "shell_exec")
        assert policy.check_tool_call("alice", "acme", "shell_exec") is False

    def test_deny_tool_other_user_unaffected(self) -> None:
        policy = FakeToolPolicy()
        policy.deny_tool("alice", "acme", "shell_exec")
        assert policy.check_tool_call("bob", "acme", "shell_exec") is True

    def test_deny_task_blocks(self) -> None:
        policy = FakeToolPolicy()
        policy.deny_task("alice", "acme", "artificer")
        assert policy.check_task_creation("alice", "acme", "artificer") is False

    def test_records_checks(self) -> None:
        policy = FakeToolPolicy()
        policy.check_tool_call("u1", "o1", "t1")
        policy.check_task_creation("u2", "o2", "a1")
        assert policy.tool_checks == [("u1", "o1", "t1")]
        assert policy.task_checks == [("u2", "o2", "a1")]


# ── CasbinToolPolicy tests ──────────────────────────────────────────


def _write_casbin_files(
    policy_lines: list[str],
) -> tuple[str, str]:
    """Write model.conf and policy.csv to a temp dir, return paths."""
    model_conf = """\
[request_definition]
r = sub, org, obj, act

[policy_definition]
p = sub, org, obj, act, eft

[policy_effect]
e = some(where (p.eft == allow)) && !some(where (p.eft == deny))

[matchers]
m = (r.sub == p.sub || p.sub == "*") && (r.org == p.org || p.org == "*") && (r.obj == p.obj || p.obj == "*") && (r.act == p.act || p.act == "*")
"""
    tmpdir = Path(tempfile.mkdtemp())
    model_path = tmpdir / "model.conf"
    policy_path = tmpdir / "policy.csv"
    model_path.write_text(model_conf)
    policy_path.write_text("\n".join(policy_lines) + "\n")
    return str(model_path), str(policy_path)


class TestCasbinToolPolicy:
    def test_satisfies_protocol(self) -> None:
        model, policy = _write_casbin_files([
            "p, *, *, *, tool_call, allow",
        ])
        tp = CasbinToolPolicy(model, policy)
        assert isinstance(tp, ToolPolicyProtocol)

    def test_wildcard_allow_all(self) -> None:
        model, policy = _write_casbin_files([
            "p, *, *, *, tool_call, allow",
            "p, *, *, *, task_create, allow",
        ])
        tp = CasbinToolPolicy(model, policy)
        assert tp.check_tool_call("anyone", "any-org", "any-tool") is True
        assert tp.check_task_creation("anyone", "any-org", "any-agent") is True

    def test_specific_deny_overrides_wildcard_allow(self) -> None:
        model, policy = _write_casbin_files([
            "p, *, *, *, tool_call, allow",
            "p, alice, acme, shell_exec, tool_call, deny",
        ])
        tp = CasbinToolPolicy(model, policy)
        assert tp.check_tool_call("alice", "acme", "shell_exec") is False
        assert tp.check_tool_call("bob", "acme", "shell_exec") is True

    def test_no_policy_denies_by_default(self) -> None:
        model, policy = _write_casbin_files([])
        tp = CasbinToolPolicy(model, policy)
        assert tp.check_tool_call("alice", "acme", "shell_exec") is False

    def test_org_scoped_policy(self) -> None:
        model, policy = _write_casbin_files([
            "p, *, acme, *, tool_call, allow",
        ])
        tp = CasbinToolPolicy(model, policy)
        assert tp.check_tool_call("alice", "acme", "shell_exec") is True
        assert tp.check_tool_call("alice", "evil-corp", "shell_exec") is False

    def test_add_and_remove_policy(self) -> None:
        model, policy = _write_casbin_files([])
        tp = CasbinToolPolicy(model, policy)
        assert tp.check_tool_call("alice", "acme", "search") is False
        tp.add_policy("alice", "acme", "search", "tool_call")
        assert tp.check_tool_call("alice", "acme", "search") is True
        tp.remove_policy("alice", "acme", "search", "tool_call")
        assert tp.check_tool_call("alice", "acme", "search") is False

    def test_reload_picks_up_file_changes(self) -> None:
        model, policy_path = _write_casbin_files([])
        tp = CasbinToolPolicy(model, policy_path)
        assert tp.check_tool_call("alice", "acme", "shell_exec") is False
        Path(policy_path).write_text(
            "p, *, *, *, tool_call, allow\n",
        )
        tp.reload_policy()
        assert tp.check_tool_call("alice", "acme", "shell_exec") is True


class TestCreateToolPolicy:
    def test_factory_with_project_config(self) -> None:
        config_dir = Path("config")
        if not (config_dir / "tool_policy_model.conf").exists():
            pytest.skip("config/tool_policy_model.conf not found")
        tp = create_tool_policy()
        assert tp.check_tool_call("test-user", "test-org", "any-tool") is True
