# Story 1.4: Inspect AI Framework Adapter

## User Story

As a **platform operator**, I want to run Inspect AI eval suites against
Stronghold agents, so that I can use a rigorous third-party eval framework with
solver/scorer/dataset abstractions rather than building everything from scratch.

## Background / Motivation

Inspect AI [EV-INSPECT-01] provides a clean solver/scorer/dataset abstraction
for agent evals with sandbox-per-sample isolation [EV-INSPECT-02]. Adopting it
as an adapter gives access to existing eval datasets and community-contributed
scorers without lock-in.

## Acceptance Criteria

- AC1: Given an Inspect AI task definition, When the adapter wraps it, Then a
  Stronghold `EvalSample` is produced with compatible input/output/metadata.
- AC2: Given a Stronghold agent, When wrapped as an Inspect AI solver, Then it
  receives task input and returns a response through the standard Inspect
  solver interface.
- AC3: Given an Inspect AI scorer, When applied to agent output, Then it returns
  a score compatible with Stronghold's eval report format.
- AC4: Given the adapter, When running an eval, Then each sample runs in
  isolation (no shared state between samples).

## Test Mapping (TDD Stubs)

| AC  | Test path                               | Test function                            | Tier  |
|-----|-----------------------------------------|------------------------------------------|-------|
| AC1 | tests/eval/test_inspect_adapter.py      | test_inspect_task_to_eval_sample         | happy |
| AC2 | tests/eval/test_inspect_adapter.py      | test_agent_as_inspect_solver             | happy |
| AC3 | tests/eval/test_inspect_adapter.py      | test_inspect_scorer_to_eval_report       | happy |
| AC4 | tests/eval/test_inspect_adapter.py      | test_sample_isolation                    | happy |

## Files to Touch

- New: `src/stronghold/eval/inspect_adapter.py`
- Modify: `src/stronghold/eval/runner.py` (adapter registration)

## Evidence References

- [EV-INSPECT-01] — solver/scorer/dataset abstraction
- [EV-INSPECT-02] — sandbox per eval sample
