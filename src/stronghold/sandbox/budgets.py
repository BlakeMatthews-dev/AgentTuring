"""Per-tenant sandbox resource budgets enforced at spawn time.

ADR-K8S-026 §budget: each tenant has a budget of concurrent sandbox pods,
total CPU, and total memory. Spawn is rejected if budget would be exceeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("stronghold.sandbox.budgets")


@dataclass
class TenantBudget:
    """Resource budget for a tenant's sandbox pods."""

    max_pods: int = 5
    max_cpu_millicores: int = 4000  # 4 vCPU total
    max_memory_mb: int = 4096  # 4GB total


class SandboxBudgetEnforcer:
    """Enforces per-tenant resource budgets at spawn time."""

    def __init__(self) -> None:
        self._budgets: dict[str, TenantBudget] = {}
        self._usage: dict[str, dict[str, int]] = {}  # tenant -> {pods, cpu_m, mem_mb}
        self._default = TenantBudget()

    def set_budget(self, tenant_id: str, budget: TenantBudget) -> None:
        self._budgets[tenant_id] = budget

    def get_budget(self, tenant_id: str) -> TenantBudget:
        return self._budgets.get(tenant_id, self._default)

    def get_usage(self, tenant_id: str) -> dict[str, int]:
        return dict(self._usage.get(tenant_id, {"pods": 0, "cpu_m": 0, "mem_mb": 0}))

    def check_spawn(
        self, tenant_id: str, cpu_millicores: int, memory_mb: int,
    ) -> tuple[bool, str]:
        """Check if a spawn would exceed budget. Returns (allowed, reason)."""
        budget = self.get_budget(tenant_id)
        usage = self._usage.get(tenant_id, {"pods": 0, "cpu_m": 0, "mem_mb": 0})

        if usage["pods"] >= budget.max_pods:
            return False, f"pod limit reached ({budget.max_pods})"

        if usage["cpu_m"] + cpu_millicores > budget.max_cpu_millicores:
            return False, (
                f"CPU budget exceeded ({usage['cpu_m']}m + {cpu_millicores}m "
                f"> {budget.max_cpu_millicores}m)"
            )

        if usage["mem_mb"] + memory_mb > budget.max_memory_mb:
            return False, (
                f"memory budget exceeded ({usage['mem_mb']}MB + {memory_mb}MB "
                f"> {budget.max_memory_mb}MB)"
            )

        return True, ""

    def record_spawn(self, tenant_id: str, cpu_millicores: int, memory_mb: int) -> None:
        usage = self._usage.setdefault(tenant_id, {"pods": 0, "cpu_m": 0, "mem_mb": 0})
        usage["pods"] += 1
        usage["cpu_m"] += cpu_millicores
        usage["mem_mb"] += memory_mb

    def record_reap(self, tenant_id: str, cpu_millicores: int, memory_mb: int) -> None:
        usage = self._usage.get(tenant_id)
        if not usage:
            return
        usage["pods"] = max(0, usage["pods"] - 1)
        usage["cpu_m"] = max(0, usage["cpu_m"] - cpu_millicores)
        usage["mem_mb"] = max(0, usage["mem_mb"] - memory_mb)
