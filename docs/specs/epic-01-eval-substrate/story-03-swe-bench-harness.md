# Story 1.3: SWE-bench Adapter

## User Story

As a **platform operator**, I want to benchmark Stronghold's coding agents
against SWE-bench, so that I have an external baseline for code-generation
quality independent of our internal evals.

## Background / Motivation

SWE-bench [EV-SWEBENCH-01] is the standard benchmark for coding agents — real
GitHub issues as test cases. Mason, Archie, and the Gatekeeper loop should be
evaluated against it. OpenHands and SWE-agent both publish SWE-bench scores,
providing direct comparison points.

## Acceptance Criteria

- AC1: Given a SWE-bench instance (repo + issue + test patch), When the adapter
  loads it, Then it produces an `EvalSample` with input (issue text), expected
  output (test patch), and metadata (repo, instance_id).
- AC2: Given a loaded SWE-bench sample, When run through the eval runner, Then
  the coding agent receives the issue and returns a patch.
- AC3: Given an agent-produced patch and a test patch, When the scorer runs, Then
  it reports pass/fail based on test-patch application success.
- AC4: Given multiple SWE-bench instances, When run as a batch, Then results
  aggregate into a pass@1 score with per-instance detail.

## Test Mapping (TDD Stubs)

| AC  | Test path                               | Test function                           | Tier  |
|-----|-----------------------------------------|-----------------------------------------|-------|
| AC1 | tests/eval/test_swebench_adapter.py     | test_load_instance_produces_eval_sample | happy |
| AC2 | tests/eval/test_swebench_adapter.py     | test_runner_dispatches_to_coding_agent  | happy |
| AC3 | tests/eval/test_swebench_adapter.py     | test_scorer_pass_on_correct_patch       | happy |
| AC4 | tests/eval/test_swebench_adapter.py     | test_batch_aggregates_pass_at_1         | happy |

## Files to Touch

- New: `src/stronghold/eval/swebench_adapter.py`
- Modify: `src/stronghold/eval/runner.py` (adapter registration)

## Evidence References

- [EV-SWEBENCH-01] — standard coding-agent benchmark
- [EV-OPENHANDS-01] — event-stream architecture for comparison baseline
