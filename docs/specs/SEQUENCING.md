# Epic Sequencing

## Ordering Rationale

Epic 01 (Eval Substrate) ships first because no other epic can claim "we did not
regress" without behavioral tagging and optimization/holdout splits. Every
downstream epic's ship gate includes an eval pass.

Epics 02–06 form a linear dependency chain building toward Conduit-as-reasoning-
agent. Each adds one layer: data model → permissions → taxonomy → tool interface
→ reasoning loop.

Epics 07–09 form a parallel track for self-improvement infrastructure: DSPy
compilation → prompt versioning (safety net) → canary + tournament (promotion
gate).

Epics 10–12 are expansion features that unlock new capabilities once the
foundation is stable.

Epic 13 (Hyperagents meta-level) ships last in the improvement track because it
edits the improvement loop itself and needs every safety net (versioning, canary,
rollback) already in place.

Epic 14 (Artificer v2) is a rethink trigger, not a build spec. It captures the
criteria under which v2 design begins — after learning from epics 06–13.

## Ship Waves

| Wave | Epics | Release constraint |
|------|-------|--------------------|
| 1 | 01 | Foundation — must ship alone |
| 2 | 02, 03 | May share a release (data model + permissions) |
| 3 | 04 | Alone — taxonomy enforcement changes factory behavior |
| 4 | 05 | Alone — agents-as-tools is a behavioral shift |
| 5 | 06 | Alone — Conduit refactor, highest risk |
| 6 | 07 | Alone — DSPy introduction |
| 7 | 08 | Alone — prompt versioning |
| 8 | 09 | Alone — canary/tournament promotion |
| 9 | 10, 11, 12 | May share a release (independent expansion) |
| 10 | 13 | Alone — meta-level self-improvement |
| 11 | 14 | Rethink trigger — document only, no code |

## Serialization Bottleneck Files

These files are modified by multiple epics. Each epic that touches them must land
in its own PR to avoid merge conflicts and review confusion:

- `src/stronghold/conduit.py` — Epics 06, 10
- `src/stronghold/security/sentinel/policy.py` — Epics 03, 05
- `src/stronghold/agents/factory.py` — Epics 04, 05
- `src/stronghold/tools/registry.py` — Epic 05
- `src/stronghold/agents/tournament.py` — Epic 09
- `src/stronghold/skills/forge.py` — Epic 13
- `src/stronghold/memory/learnings/promoter.py` — Epic 13
