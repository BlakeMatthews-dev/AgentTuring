# Turing Field Console — specs index

**Parent PR:** [#1177](https://github.com/Agent-StrongHold/stronghold/pull/1177) — the UI rewrite that replaces Stronghold's medieval multi-tenant dashboard with Agent Turing's four-surface field console (plus Memory inspector + design canvas).

**Context:** `project_turing.research.md` (repo root) is the research narrative for the autonoetic self this console operates on. The `research/project-turing/` branch carries that self-model's own specs — 30 of them — and is architecturally incompatible with main's multi-tenant posture. The specs in *this* file are the **console layer** that sits above the self-model: they do not modify the 7-tier memory, they give the handler a surface to read/inspect/publish/edit the self's artifacts.

## The six specs

In dependency order (read top-to-bottom; implementation order is the same):

| # | Spec | Realises |
|---|------|----------|
| 1178 | [`turing-obsidian-store.yaml`](turing-obsidian-store.yaml) | ObsidianStore protocol + filesystem impl + fake + four tools (read/write/append/search). Working-memory substrate for self-talk and scratch reasoning. |
| 1179 | [`turing-wordpress-publishing.yaml`](turing-wordpress-publishing.yaml) | WordPressClient protocol + REST impl + `wordpress_publish` tool + bundled WP/MariaDB docker-compose services. Autonomous publishing for the Blog surface. |
| 1180 | [`turing-memory-consolidator.yaml`](turing-memory-consolidator.yaml) | Consolidator that promotes recurring patterns from Obsidian into the 7-tier store. Reuses the existing `LearningStore` auto-promote path; closes the two-tier memory loop. Depends on 1178. |
| 1181 | [`turing-memory-crud-endpoints.yaml`](turing-memory-crud-endpoints.yaml) | API endpoints backing the Memory surface: tier list, row detail, edit, promote/demote/expire/burn, audit-flag surfaces for F1/F4/F13/F18. |
| 1182 | [`turing-chat-streaming.yaml`](turing-chat-streaming.yaml) | SSE streaming endpoint for the Chat surface, daily initiation budget (Turing-initiated threads ≤ 1/day), inline memory citations, typewriter reveal. |
| 1183 | [`turing-notebook-live-vault.yaml`](turing-notebook-live-vault.yaml) | Handler-facing notebook API over Turing's Obsidian vault. Depends on 1178. |

## What is NOT in these specs

- **Self-model tools** (`note_passion`, `write_self_todo`, `record_personality_claim`, activation-graph authorship). Those live in the `research/project-turing/` branch. The audit findings F1/F4/F13/F18 referenced by the Memory UI originate there.
- **7-tier memory internals** (episodic/semantic/biographical/regret/affirmation/wisdom storage). Already implemented; this console reads/writes to it through existing protocols (`EpisodicMemoryStore`, `LearningStore`).
- **Warden / Sentinel / Gate semantics.** Already implemented; the new tools and endpoints hook into the existing boundary layer, they do not redefine it.

## Two-tier memory architecture

The Turing console realises a two-tier split on the write side of memory:

| Tier | Substrate | Role | Write point |
|------|-----------|------|-------------|
| Working memory | Obsidian vault (markdown on disk) | Self-talk, scratch reasoning, drafts, dreams/hobbies/passions journaling | `obsidian_append`/`obsidian_write` tools — called liberally during reasoning |
| Persistent recall | 7-tier vector DB (existing) | Authoritative long-term memory | Memory consolidator (spec 1180) — promotes recurring patterns from Obsidian; existing `LearningStore` extractor — promotes from tool history |

Obsidian is durable on disk but not authoritative. The consolidator decides what crosses over. Source notes are never deleted — Turing can reread raw thoughts and notice patterns the consolidator missed.

## Build-rule compliance checklist

Per CLAUDE.md §Build Rules, every spec above is constrained by:

- **No Code Without Architecture** — this README and the YAML specs are the architecture.
- **No Code Without Tests (TDD)** — each spec's `acceptance_criteria` become failing tests before implementation starts.
- **No Hardcoded Secrets** — WordPress credentials + Obsidian vault path come from env/config; all defaults are example values.
- **No Direct External Imports in Business Logic** — protocols in `src/stronghold/protocols/`, impls behind DI, never imported directly.
- **Every Protocol Needs a Noop/Fake** — `tests/fakes.FakeObsidianStore` and `tests/fakes.FakeWordPressClient` are acceptance criteria.
- **Security Review Gates** — phases 3/7/10 per ARCHITECTURE.md §3.6; the Memory CRUD endpoints (1181) and the WordPress publish tool (1179) both sit on security boundaries and need a pre-merge review.
- **No Co-Authored-By Lines** — kept.

## Implementation order

1. **1178** first — nothing else works without ObsidianStore.
2. **1179** and **1182** in parallel — both depend only on existing infra.
3. **1183** after 1178 — notebook consumes the obsidian store.
4. **1181** after the Memory UI's shape is settled (no hard dep, but the audit-flag surfaces are easier to wire once row retrieval is stable).
5. **1180** last — closes the loop; needs real data in the vault to be meaningful.

Each spec is one PR. Each PR lands green (pytest + ruff + mypy --strict + bandit). Security-boundary specs (1179, 1181) get a pre-merge review per §3.6.
