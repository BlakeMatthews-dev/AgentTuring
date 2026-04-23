# Story 13.2: Meta Safety Circuit Breaker

## User Story

As a **platform operator**, I want a circuit breaker that freezes meta-level
self-mutation if changes happen too rapidly, so that a runaway optimization
loop cannot destabilize the system.

## Background / Motivation

Self-referential improvement systems can enter feedback loops where rapid
mutations compound into unpredictable behavior. The circuit breaker is a
simple safety primitive: if more than N meta-mutations happen within a time
window, the meta-improvement flag auto-disables and an alert fires. This is
analogous to a rate limiter, but for self-modification.

## Acceptance Criteria

- AC1: Given a circuit breaker configured at 5 mutations/hour, When the 6th
  mutation fires within the hour, Then the meta-improvement flag is disabled
  and an alert is emitted.
- AC2: Given the circuit breaker has tripped, When the time window resets,
  Then the flag remains disabled until manually re-enabled (not auto-resume).
- AC3: Given a tripped circuit breaker, When the platform operator reviews,
  Then the audit log shows all mutations that led to the trip with timestamps
  and provenance.
- AC4: Given the circuit breaker, When mutations happen at a rate below the
  threshold, Then no intervention occurs.

## Test Mapping (TDD Stubs)

| AC  | Test path                           | Test function                                 | Tier     |
|-----|-------------------------------------|-----------------------------------------------|----------|
| AC1 | tests/meta/test_circuit_breaker.py  | test_breaker_trips_on_excess_mutations        | critical |
| AC2 | tests/meta/test_circuit_breaker.py  | test_tripped_requires_manual_reenable         | critical |
| AC3 | tests/meta/test_circuit_breaker.py  | test_audit_log_on_trip                        | happy    |
| AC4 | tests/meta/test_circuit_breaker.py  | test_below_threshold_no_intervention          | happy    |

## Files to Touch

- New: `src/stronghold/meta/circuit_breaker.py`

## Evidence References

- [EV-HYPERAGENTS-02] — self-referential systems need bounded modification rates
