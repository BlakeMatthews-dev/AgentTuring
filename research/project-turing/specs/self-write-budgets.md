# Spec 37 — Per-request self-write budgets (G2)

*Hard caps on how much self-model mutation a single request can produce. Closes F20.*

**Depends on:** [self-tool-registry.md](./self-tool-registry.md), [self-write-preconditions.md](./self-write-preconditions.md), [conduit-runtime.md](./conduit-runtime.md).
**Depended on by:** [operator-review-gate.md](./operator-review-gate.md).

---

## Current state

A single perception or observation turn can call `note_passion`, `note_hobby`, etc. unbounded times. An adversarial LLM can flood every self-model table in one request.

## Target

A `RequestWriteBudget` context object, bound via `contextvars` at the start of every perception/observation, with per-category counters. Each tool decrements its counter; exhaustion raises `SelfWriteBudgetExceeded`. Counters reset per request.

## Acceptance criteria

### Budget shape

- **AC-37.1.** `RequestWriteBudget` has counters:
  - `new_nodes` (passion / hobby / interest / preference / skill combined): 3
  - `contributors` (self-origin contributors): 5
  - `todo_writes` (write/revise/complete/archive): 2
  - `personality_claims`: 3
  Defaults are tunable at runtime. Test each cap.
- **AC-37.2.** `RequestWriteBudget.new()` returns a fresh instance with all counters at defaults. Test.

### Context binding

- **AC-37.3.** `_request_budget_var: ContextVar[RequestWriteBudget]` is set at the start of each request pipeline (spec 44), reset at end. A write-tool called outside a pipeline context instantiates a default budget (tests, scripts). Test.
- **AC-37.4.** `with use_budget(budget):` context manager binds and unbinds the var. Test bind/unbind around a nested tool call.

### Decrement semantics

- **AC-37.5.** Each tool decrements its counter **before** the repo write. If the counter is already at zero, raise `SelfWriteBudgetExceeded(category)`. No partial writes. Test.
- **AC-37.6.** A successful tool call that raises on a post-decrement step (e.g., Warden block) restores the counter. Budget is "budget for successful writes," not "budget for attempts." Test.
- **AC-37.7.** Tool-to-category map:
  - `note_passion/hobby/interest/preference/skill` → `new_nodes`
  - `write_contributor` → `contributors`
  - `write_self_todo`, `revise_self_todo`, `complete_self_todo`, `archive_self_todo` → `todo_writes` (each counts one)
  - `record_personality_claim` → `personality_claims`
  Test each category.
- **AC-37.8.** `rerank_passions`, `practice_skill`, `downgrade_skill`, `note_engagement`, `note_interest_trigger` are NOT budget-counted — they mutate existing state without adding surface. Test.

### Observability

- **AC-37.9.** On exhaustion, emit a Prometheus counter `turing_self_write_budget_exceeded_total{category, self_id}`. Test.
- **AC-37.10.** Mirror an OBSERVATION: `"budget exceeded on {category}; attempted write rejected"`, `intent_at_time = "budget exceeded"`. Test.

### Edge cases

- **AC-37.11.** Budget is process-local; no cross-request leakage is possible because the `ContextVar` scope is the request. Test concurrent requests do not share budget.
- **AC-37.12.** Nested contexts (observation step following perception step within the same request) share the same budget — they are the same request. Spec 44 wires this. Test.
- **AC-37.13.** Budget defaults are loaded from `config/turing.yaml` at startup, overrideable per deployment. Test with a non-default config.

## Implementation

```python
# self_budget.py

from dataclasses import dataclass, replace
from contextvars import ContextVar


@dataclass
class RequestWriteBudget:
    new_nodes: int = 3
    contributors: int = 5
    todo_writes: int = 2
    personality_claims: int = 3

    @classmethod
    def new(cls) -> "RequestWriteBudget":
        return cls()


_request_budget_var: ContextVar[RequestWriteBudget | None] = ContextVar(
    "request_budget", default=None,
)


class SelfWriteBudgetExceeded(Exception):
    def __init__(self, category: str):
        self.category = category


def _consume(category: str) -> None:
    budget = _request_budget_var.get() or RequestWriteBudget.new()
    current = getattr(budget, category)
    if current <= 0:
        raise SelfWriteBudgetExceeded(category)
    setattr(budget, category, current - 1)


def _refund(category: str) -> None:
    budget = _request_budget_var.get()
    if budget is None:
        return
    setattr(budget, category, getattr(budget, category) + 1)
```

Each budget-gated tool:
```python
def note_passion(repo, self_id, text, strength, new_id, ...):
    _require_ready(repo, self_id)
    _warden_gate_self_write(text, "note passion", self_id=self_id)
    _consume("new_nodes")
    try:
        return _do_note_passion(...)
    except Exception:
        _refund("new_nodes")
        raise
```

## Open questions

- **Q37.1.** Defaults (3/5/2/3) are calibrated for a perception step that has a few legitimate noticings. Observation step may need different limits. A per-step budget (perception vs observation) is worth considering.
- **Q37.2.** `rerank_passions` bypasses budgets; a self that re-ranks unboundedly could still churn the minimal-block passion line. Add a rerank counter (e.g. ≤2/request) if that becomes an abuse vector.
- **Q37.3.** Refund-on-failure is generous. Alternative: once consumed, always consumed. Current spec leans generous because a Warden block is not the self's fault — the LLM tried within the budget.
