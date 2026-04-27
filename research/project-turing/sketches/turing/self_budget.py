"""Per-request self-write budgets. See specs/self-write-budgets.md.

Caps: 3 new nodes, 5 contributors, 2 todo writes, 3 personality claims
per request cycle. ContextVar-backed; zero → SelfWriteBudgetExceeded.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field


@dataclass
class RequestWriteBudget:
    new_nodes: int = 3
    contributors: int = 5
    todo_writes: int = 2
    personality_claims: int = 3

    @classmethod
    def fresh(cls) -> RequestWriteBudget:
        return cls()


class SelfWriteBudgetExceeded(Exception):
    def __init__(self, category: str, remaining: int) -> None:
        self.category = category
        self.remaining = remaining
        super().__init__(f"budget exceeded for {category}: {remaining} remaining")


_budget_var: contextvars.ContextVar[RequestWriteBudget | None] = contextvars.ContextVar(
    "_request_write_budget", default=None
)

_BUDGET_EXCEEDED_COUNTS: dict[str, int] = {}


def get_budget() -> RequestWriteBudget | None:
    return _budget_var.get()


def use_budget(budget: RequestWriteBudget):
    class _Binder:
        def __enter__(self):
            self._token = _budget_var.set(budget)
            return budget

        def __exit__(self, *exc):
            _budget_var.reset(self._token)

    return _Binder()


def consume(category: str) -> None:
    budget = _budget_var.get()
    if budget is None:
        return
    remaining = getattr(budget, category, None)
    if remaining is None:
        return
    if remaining <= 0:
        key = f"{category}"
        _BUDGET_EXCEEDED_COUNTS[key] = _BUDGET_EXCEEDED_COUNTS.get(key, 0) + 1
        raise SelfWriteBudgetExceeded(category, remaining)
    setattr(budget, category, remaining - 1)


def refund(category: str) -> None:
    budget = _budget_var.get()
    if budget is None:
        return
    current = getattr(budget, category, None)
    if current is not None:
        setattr(budget, category, current + 1)


def get_exceeded_counts() -> dict[str, int]:
    return dict(_BUDGET_EXCEEDED_COUNTS)
