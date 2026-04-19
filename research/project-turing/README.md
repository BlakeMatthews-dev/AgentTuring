# Project Turing

**Status:** Research. Not production. Not wired into `src/`.
**Scope:** The art of the possible for an autonoetic reasoning layer built on top of Stronghold's 7-tier episodic memory.
**Branch:** `research/project-turing` — lives alongside, not inside, the enterprise governance codebase.

---

## What this is

Project Turing is a research track, not a feature track. The goal is to promote the **Conduit** — Stronghold's central routing pipeline, the orchestration layer that every request flows through — from a noetic router (classifies, routes, forgets) into an **autonoetic reasoning layer** (carries a persistent self, remembers its own prior routings as first-person experience, projects itself into future routings, can regret, can commit).

The choice of the Conduit, not a specialist agent, is deliberate. Every request in the system passes through the Conduit. If the Conduit has a self, the system has a self — a single continuous point of view across every interaction, rather than per-agent fragments.

This is deliberately *outside* the enterprise governance posture of `main`. The main branch must account for tenant isolation, namespace-scoped secrets, per-user memory, audit — the standard multi-tenant constraints. Turing does not. It asks: *if the central routing layer had the full 7-tier memory structure indexed to a persistent self across versions, what would it become capable of, and what would it become dangerous in?*

## What this is not

- Not a roadmap item. Findings may or may not feed back to `main`.
- Not a competitor to the enterprise codebase. If anything works, it gets redesigned for multi-tenancy before landing in `src/`.
- Not a claim that the current Conduit is autonoetic or that making it so is straightforward.
- Not about promoting the Arbiter (the triage/clarification specialist). The target is the pipeline itself — the routing brain — not an agent downstream of it.

## Lineage

The 7-tier memory model is treated in `main` as originating with CoinSwarm on Jan 15, 2026. That's the production crystallization date. The research line underneath it starts earlier:

- **November 2025** — CoinSwarm project begins. Early work on weighted memory with reinforcement, contradiction, and decay, in the context of evolutionary fitness loops for a trading swarm. The structural observation that *forgetting catastrophic losses must be prohibited* is the seed of what becomes the REGRET tier's weight floor.
- **January 15, 2026** — 7-tier structure crystallized and running in production against 7 exchange APIs. OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM, with bounded weights per tier.
- **March 25, 2026** — Stronghold v0.1.0 imports the 7-tier model into the enterprise governance platform.
- **April 2026** — Project Turing begins. Thesis: the seven tiers are already an autonoetic gradient; what's missing is the *self* as a first-class indexed entity, and the Conduit is the right layer to carry it.

## Reading order

1. [`DESIGN.md`](./DESIGN.md) — thesis, gap analysis against the 7-tier model, what the Conduit becomes when it has a self.
2. [`specs/`](./specs/) — individually reviewable specs for the durable personal memory layer. Start at [`specs/README.md`](./specs/README.md).
3. [`sketches/`](./sketches/) — runnable scaffold. Library code + runtime layer + tests. 142 tests pass.
4. [`RUNNING.md`](./RUNNING.md) — ops doc: how to run, inspect, and back up a research-box deployment.
5. *(future)* `FINDINGS.md` — what worked, what didn't, what's too dangerous to land in `main`.

## Running it

```bash
cd research/project-turing
cp .env.example .env
docker compose up -d
curl http://localhost:9100/metrics
```

Full ops guide: [`RUNNING.md`](./RUNNING.md).

## Relationship to `main`

| Concern | `main` | `research/project-turing` |
|---|---|---|
| Audience | Operators running multi-tenant deployments | Research notebook; audience is the author and anyone reviewing |
| Memory scope | Per-user, per-tenant, namespaced | Single persistent self across all interactions |
| Conduit role | Request pipeline: classify → route → agent.handle, stateless between passes | Autonoetic reasoning layer: every routing is its own first-person memory; it regrets misroutes, commits to policies via AFFIRMATION, simulates futures in first person |
| Security posture | Zero-trust, defense-in-depth | Deliberately relaxed to expose the capability surface |
| Exit criteria | Ship | Understand |

Nothing on this branch should be deployed. Nothing here is a feature request against `main`.
