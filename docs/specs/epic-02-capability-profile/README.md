# Epic 02: CapabilityProfile

## Summary

Introduce the `CapabilityProfile` data structure: a per-agent record mapping
`(capability, intent_class)` to three orthogonal dimensions — permission
(binary), skill score (continuous, outcome-derived), and cost vector (composite,
measured). This is the data model reasoning agents consume when deciding
self-execute vs delegate vs decline.

## Why Now

Epic 01 (Eval Substrate) provides the measurement infrastructure for validating
that skill scores and cost vectors actually improve routing decisions. Without
eval, these would be untestable priors.

## Depends On

- Epic 01 (Eval Substrate)

## Blocks

- Epic 03 (Agent-Call ACLs) — ACLs extend the permission dimension
- Epic 04 (Taxonomy) — light/heavy distinction uses the profile
- Epic 05 (Agents-as-Tools) — tool descriptors generated from profiles

## Ship Gate

CapabilityProfile round-trips (serialize → persist → load → verify) for all
shipped agents. Skill scores populate from declared priors; cost vectors populate
from container specs.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Configures initial skill priors and cost vectors per agent |
| Agent author | Declares capabilities and initial skill estimates in agent.yaml |
| Tenant admin | Views per-agent capability breakdown for their org |

## Evidence References

- [EV-HYPERAGENTS-02] — per-capability scoring beyond binary permissions
- [EV-FRUGAL-01] — cost-aware routing needs a cost data model
- [EV-LC-DEEP-05] — profile schema precedent in deepagents

## Files Touched

### New Files
- `src/stronghold/capability/__init__.py`
- `src/stronghold/capability/profile.py` — CapabilityProfile, SkillScore, CostVector dataclasses
- `src/stronghold/capability/store.py` — in-memory store (protocol-backed for PostgreSQL later)
- `src/stronghold/capability/updater.py` — skill-score update from eval outcomes
- `tests/capability/test_profile_schema.py`
- `tests/capability/test_store.py`
- `tests/capability/test_updater.py`

### Modified Files
- `src/stronghold/types/` — add CapabilityProfile types
- `src/stronghold/container.py` — register capability store
- `agents/*/agent.yaml` — add `capabilities:` section with initial priors
- `tests/fakes.py` — add FakeCapabilityStore

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_CAPABILITY_PROFILE_ENABLED`
- **Canary cohort**: Internal dev org — profiles are read-only data, no behavioral change
- **Rollback plan**: Disable flag; routing falls back to existing heuristic (no profile consultation)

## Open Questions

- OQ-CAP-01: Skill-score decay function
- OQ-CAP-02: Cost-vector aggregation across nested calls
- OQ-CAP-03: Cold-start exploration policy
