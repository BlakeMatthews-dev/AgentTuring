# Epic 14: Artificer v2 Rethink Trigger

## Summary

This is a rethink trigger, not a build spec. Artificer was the v1 code-gen
agent; the current loop is Gatekeeper + Archie + Mason + Auditor. This epic
captures: (1) learnings from the v1→current transition, (2) formal retirement
of the Artificer YAML, (3) documentation of the current loop's contracts, and
(4) the criteria that trigger v2 design — so we don't pre-commit to an
architecture before learning from Epics 06–13.

## Why Now

This epic ships last because its value is in waiting. The Conduit-as-reasoning-
agent (Epic 06), DSPy (Epic 07), Canary/Tournament (Epic 09), and Hyperagents
meta-level (Epic 13) all generate design signal for what v2 should look like.
Writing the v2 spec before learning from those epics would repeat v1's mistake.

## Depends On

- Epic 06 (Conduit-as-Reasoning-Agent) — reasoning loop learnings
- Epic 07 (DSPy Task Signatures) — compilation effectiveness data
- Epic 09 (Canary + Tournament) — staged promotion data
- Epic 13 (Hyperagents Meta-Level) — meta-improvement learnings

## Blocks

Nothing — this is a terminal epic.

## Ship Gate

- V1 learnings documented (what worked, what didn't, why we replaced it)
- Artificer agent.yaml retired (removed from agents/ or moved to archive/)
- Gatekeeper + Archie + Mason + Auditor contracts documented
- V2 design-freeze criteria defined and measurable

## Roles Affected

| Role | Impact |
|------|--------|
| Agent author | Understands the canonical code-gen loop |
| Platform operator | Knows the retirement status of Artificer v1 |

## Evidence References

- [EV-HYPERAGENTS-03] — generational evolution: learn from generation N before designing N+1
- [EV-SWEBENCH-01] — benchmark baseline for v1 vs current vs future v2

## Files Touched

### New Files
- `docs/specs/epic-14-artificer-v2-rethink/v1-learnings.md` — retrospective document
- `docs/specs/epic-14-artificer-v2-rethink/current-loop-contracts.md` — Gatekeeper/Archie/Mason/Auditor
- `docs/specs/epic-14-artificer-v2-rethink/v2-design-freeze-criteria.md`

### Modified Files
- `agents/artificer/agent.yaml` — mark deprecated or move to `agents/_archive/`

## Incremental Rollout Plan

- **Feature flag**: None — this is a document-only epic
- **Canary cohort**: N/A
- **Rollback plan**: N/A — documents only

## Open Questions

- OQ-ART-01: Gatekeeper vs Warden role boundary
- OQ-ART-02: Criteria for "enough learning" to trigger v2 design freeze
