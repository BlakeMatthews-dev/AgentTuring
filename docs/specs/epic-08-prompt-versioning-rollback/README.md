# Epic 08: Prompt Versioning + Rollback

## Summary

Version every prompt (hand-written and DSPy-compiled) so that promotions are
reversible. Provide a rollback API that restores a previous version and
re-validates against the holdout eval set. Maintain an audit log of all prompt
changes with provenance (human edit, DSPy compilation, SkillForge mutation).

## Why Now

Epic 07 (DSPy) introduces automated prompt mutation. Without versioning, a bad
compilation is irrecoverable. This epic is the safety net that makes DSPy and
Hyperagents (Epic 13) meta-level improvement safe to run in production.

## Depends On

- Epic 07 (DSPy Task Signatures) — prompt changes to version

## Blocks

- Epic 09 (Canary + Tournament) — canary needs a version to promote and a version to rollback to
- Epic 13 (Hyperagents Meta-Level) — meta-improvements need versioned rollback

## Ship Gate

A prompt is versioned, mutated, rolled back, and the rolled-back version passes
its eval.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Reviews prompt change history, triggers rollback |
| Security auditor | Audits prompt mutation provenance |

## Evidence References

- [EV-HYPERAGENTS-03] — genealogy tracking per generation
- [EV-LC-DEEP-04] — regression protection requires known-good baseline to revert to

## Files Touched

### New Files
- `src/stronghold/prompts/versioning/__init__.py`
- `src/stronghold/prompts/versioning/store.py` — versioned prompt store
- `src/stronghold/prompts/versioning/rollback.py` — rollback API
- `src/stronghold/prompts/versioning/audit.py` — change audit log
- `tests/prompts/versioning/test_store.py`
- `tests/prompts/versioning/test_rollback.py`
- `tests/prompts/versioning/test_audit.py`

### Modified Files
- `src/stronghold/skills/forge.py` — emit version events on mutation
- `src/stronghold/dspy/compiler.py` — emit version events on compilation
- `src/stronghold/container.py` — register versioned prompt store

## Incremental Rollout Plan

- **Feature flag**: `STRONGHOLD_PROMPT_VERSIONING_ENABLED`
- **Canary cohort**: All (versioning is read/write infra, not behavioral change)
- **Rollback plan**: Disable flag; prompts load without version tracking (current behavior)

## Open Questions

- OQ-PROMPT-01: Rollback granularity (per-agent, per-signature, per-version tag)
- OQ-PROMPT-02: Version retention before GC
