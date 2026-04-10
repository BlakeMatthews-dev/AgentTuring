"""Tests for SandboxBudgetEnforcer (ADR-K8S-026)."""

from __future__ import annotations

from stronghold.sandbox.budgets import SandboxBudgetEnforcer, TenantBudget


def test_default_budget_allows_spawn() -> None:
    enforcer = SandboxBudgetEnforcer()
    allowed, reason = enforcer.check_spawn("acme", cpu_millicores=500, memory_mb=256)
    assert allowed is True
    assert reason == ""


def test_pod_limit_enforced() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_pods=2))
    enforcer.record_spawn("acme", 500, 256)
    enforcer.record_spawn("acme", 500, 256)
    allowed, reason = enforcer.check_spawn("acme", 500, 256)
    assert allowed is False
    assert "pod limit" in reason


def test_cpu_budget_enforced() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_cpu_millicores=1000))
    enforcer.record_spawn("acme", 600, 256)
    allowed, reason = enforcer.check_spawn("acme", 600, 256)
    assert allowed is False
    assert "CPU budget" in reason


def test_memory_budget_enforced() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_memory_mb=512))
    enforcer.record_spawn("acme", 500, 300)
    allowed, reason = enforcer.check_spawn("acme", 500, 300)
    assert allowed is False
    assert "memory budget" in reason


def test_reap_frees_resources() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_pods=1))
    enforcer.record_spawn("acme", 500, 256)
    assert enforcer.check_spawn("acme", 500, 256)[0] is False

    enforcer.record_reap("acme", 500, 256)
    assert enforcer.check_spawn("acme", 500, 256)[0] is True


def test_usage_tracking() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.record_spawn("acme", 500, 256)
    enforcer.record_spawn("acme", 300, 128)
    usage = enforcer.get_usage("acme")
    assert usage["pods"] == 2
    assert usage["cpu_m"] == 800
    assert usage["mem_mb"] == 384


def test_usage_empty_tenant() -> None:
    enforcer = SandboxBudgetEnforcer()
    usage = enforcer.get_usage("new-tenant")
    assert usage == {"pods": 0, "cpu_m": 0, "mem_mb": 0}


def test_tenant_isolation() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_pods=1))
    enforcer.record_spawn("acme", 500, 256)
    # Acme is at limit, but evil-corp should be unaffected
    assert enforcer.check_spawn("acme", 500, 256)[0] is False
    assert enforcer.check_spawn("evil-corp", 500, 256)[0] is True


def test_reap_nonexistent_tenant() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.record_reap("nonexistent", 500, 256)  # Should not raise


def test_reap_does_not_go_negative() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.record_spawn("acme", 500, 256)
    enforcer.record_reap("acme", 1000, 1000)
    usage = enforcer.get_usage("acme")
    assert usage["pods"] == 0
    assert usage["cpu_m"] == 0
    assert usage["mem_mb"] == 0


def test_pod_limit_at_exact_boundary() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_pods=2))
    enforcer.record_spawn("acme", 100, 64)
    allowed, _ = enforcer.check_spawn("acme", 100, 64)
    assert allowed is True
    enforcer.record_spawn("acme", 100, 64)
    allowed, reason = enforcer.check_spawn("acme", 100, 64)
    assert allowed is False
    assert "pod limit" in reason


def test_cpu_at_exact_limit_passes() -> None:
    enforcer = SandboxBudgetEnforcer()
    enforcer.set_budget("acme", TenantBudget(max_cpu_millicores=1000))
    enforcer.record_spawn("acme", 500, 64)
    allowed, _ = enforcer.check_spawn("acme", 500, 64)
    assert allowed is True
    allowed, _ = enforcer.check_spawn("acme", 501, 64)
    assert allowed is False
