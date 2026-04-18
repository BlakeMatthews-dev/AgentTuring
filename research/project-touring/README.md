# Project Touring

**Status:** Research. Not production. Not wired into `src/`.
**Scope:** The art of the possible for an autonoetic reasoning agent built on top of Stronghold's 7-tier episodic memory.
**Branch:** `research/project-touring` — lives alongside, not inside, the enterprise governance codebase.

---

## What this is

Project Touring is a research track, not a feature track. The goal is to promote the **Arbiter** — Stronghold's central triage/routing agent — from a noetic router (knows task types, delegates) into an **autonoetic reasoner** (has a persistent self, remembers being a past actor, projects itself into future episodes, can regret, can commit).

This is deliberately *outside* the enterprise governance posture of `main`. The main branch must account for tenant isolation, namespace-scoped secrets, per-user memory, audit — the standard multi-tenant constraints. Touring does not. It asks: *if a single long-lived agent had the full 7-tier memory structure indexed to a persistent self across versions, what would it become capable of, and what would it become dangerous in?*

## What this is not

- Not a roadmap item. Findings may or may not feed back to `main`.
- Not a competitor to the enterprise codebase. If anything works, it gets redesigned for multi-tenancy before landing in `src/`.
- Not a claim that the current Arbiter is autonoetic or that making it so is straightforward.

## Lineage

The 7-tier memory model is treated in `main` as originating with CoinSwarm on Jan 15, 2026. That's the production crystallization date. The research line underneath it starts earlier:

- **November 2025** — CoinSwarm project begins. Early work on weighted memory with reinforcement, contradiction, and decay, in the context of evolutionary fitness loops for a trading swarm. The structural observation that *forgetting catastrophic losses must be prohibited* is the seed of what becomes the REGRET tier's weight floor.
- **January 15, 2026** — 7-tier structure crystallized and running in production against 7 exchange APIs. OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM, with bounded weights per tier.
- **March 25, 2026** — Stronghold v0.1.0 imports the 7-tier model into the enterprise governance platform.
- **April 2026** — Project Touring begins. Thesis: the seven tiers are already an autonoetic gradient; what's missing is the *self* as a first-class indexed entity.

## Reading order

1. `DESIGN.md` — thesis, gap analysis against the 7-tier model, what the Arbiter becomes when it has a self.
2. *(future)* `sketches/` — runnable prototypes in isolation. None of these import from `src/stronghold/`.
3. *(future)* `FINDINGS.md` — what worked, what didn't, what's too dangerous to land in `main`.

## Relationship to `main`

| Concern | `main` | `research/project-touring` |
|---|---|---|
| Audience | Operators running multi-tenant deployments | Research notebook; audience is the author and anyone reviewing |
| Memory scope | Per-user, per-tenant, namespaced | Single persistent self across all interactions |
| Arbiter role | Triage + clarify + delegate | Autonoetic reasoner: remembers past routings as *its own* acts, regrets misroutes, commits to policies via AFFIRMATION |
| Security posture | Zero-trust, defense-in-depth | Deliberately relaxed to expose the capability surface |
| Exit criteria | Ship | Understand |

Nothing on this branch should be deployed. Nothing here is a feature request against `main`.
