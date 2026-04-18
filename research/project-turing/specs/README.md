# Project Turing — Specs

Individually reviewable specs for the durable personal memory layer. Each spec owns its acceptance criteria and its implementation guidance. Specs are small on purpose; a reviewer should be able to hold one in mind at once.

**Branch:** `research/project-turing` (research only; not for `main`).
**Parent doc:** [`../DESIGN.md`](../DESIGN.md).

---

## Specs in this directory

Read in order. Later specs depend on earlier ones.

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 1 | [`schema.md`](./schema.md) | Field additions to `EpisodicMemory`; the `SourceKind` enum. | — |
| 2 | [`tiers.md`](./tiers.md) | Add `ACCOMPLISHMENT`. Revised 8-tier set with weight bounds and inheritance priority. | 1 |
| 3 | [`durability-invariants.md`](./durability-invariants.md) | The eight invariants enforced for REGRET, ACCOMPLISHMENT, WISDOM. | 1, 2 |
| 4 | [`write-paths.md`](./write-paths.md) | Write triggers and actions for REGRET, ACCOMPLISHMENT, AFFIRMATION. | 1, 2, 3 |
| 5 | [`wisdom-write-path.md`](./wisdom-write-path.md) | **Deferred.** Placeholder declaring that no write path into WISDOM exists until the dreaming spec lands. | 1, 2, 3 |
| 6 | [`retrieval.md`](./retrieval.md) | Reserved quota, source-filtered views, lineage-aware retrieval. | 1, 2, 3 |
| 7 | [`daydreaming.md`](./daydreaming.md) | Idle-compute imagination. I_IMAGINED writes only; cannot reach durable tiers. | 1, 2, 3, 6 |
| 8 | [`persistence.md`](./persistence.md) | `durable_memory` table, version migration, `self_id` minting. | 1, 2, 3 |

## Deferred

- **Dreaming** — scheduled nightly consolidation that walks durable memories, extracts patterns, and produces WISDOM candidates. Acknowledged in [`wisdom-write-path.md`](./wisdom-write-path.md) as the blocker for WISDOM writes. A separate spec will land when the work is prioritized.

## Non-goals (all specs)

- Multi-tenant scoping.
- Per-user memory.
- Backward compatibility with `src/stronghold/memory/`.
- Production deployment.

## Lineage

The 7-tier memory model originated in CoinSwarm (begun November 2025) and crystallized January 15, 2026. Stronghold imported it March 25, 2026. Project Turing's extension to durable personal memory follows from that research line; see [`../DESIGN.md`](../DESIGN.md) for the full thesis and Tulving-taxonomy mapping.
