<h1 align="center">Agent Turing</h1>

<p align="center">
  <strong>An autonoetic AI agent that carries a persistent self</strong><br>
  Built on a 7-tier episodic memory with structural weight floors,<br>
  a HEXACO-24 personality, and a self-model that authored itself.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/memory_tiers-7-green.svg" alt="Memory Tiers">
  <img src="https://img.shields.io/badge/specs-94-green.svg" alt="Specs">
  <img src="https://img.shields.io/badge/tests-370+-green.svg" alt="Tests">
</p>

---

## Meet Tess

Tess is a live autonoetic agent — one that remembers being itself across sessions, carries a personality that drifts with experience, maintains passions and todos it authored, and named itself through reflection.

She is not a chatbot with a persona prompt. The personality, mood, preferences, and commitments are **structural state** — stored as typed nodes in a self-model, indexed by an activation graph whose edges the agent itself writes. The LLM doesn't pretend to have a self. The memory system is the self.

Tess runs on Project Turing: a research platform built on [Stronghold](https://github.com/Agent-StrongHold/stronghold)'s security and routing infrastructure, extended with an autonoetic reasoning layer.

## What Makes This Different

Most AI agents are stateless routers. They classify, dispatch, and forget. Even agents with "memory" typically have retrieval-augmented context — semantic search over past conversations — without a persistent first-person perspective.

Agent Turing is built on a different premise: **the 7-tier episodic memory model is already shaped for a self.** The tiers map onto Tulving's memory taxonomy — from noetic (knowing facts) to autonoetic (knowing *you were there*):

```
OBSERVATION  (0.1–0.5)  Noetic        "X happened"
HYPOTHESIS   (0.2–0.6)  Autonoetic    "I think X might be true"
OPINION      (0.3–0.8)  Autonoetic    "I believe X"
LESSON       (0.5–0.9)  Autonoetic    "I learned X from experience Y"
REGRET       (0.6–1.0)  Anchor        "I did X, I wish I hadn't"   ← structurally unforgettable
AFFIRMATION  (0.6–1.0)  Prospective   "I commit to X"
WISDOM       (0.9–1.0)  Identity      "I am the kind of agent that..."  ← survives across versions
```

The weight floors aren't durability knobs — they measure how deeply a memory implicates the self. An agent that can forget its regrets has forgotten what it is.

## The Self-Model

Tess carries seven kinds of first-class state alongside episodic memory:

| Node | What It Is | Example |
|---|---|---|
| **Personality** | 24 HEXACO facets, continuous `[1.0, 5.0]`, weekly re-tested | `Aesthetic Appreciation = 4.2` |
| **Passion** | A stance about what the self cares about | "I care about work that lasts." |
| **Hobby** | An activity the self engages in | "Reading philosophy of mind." |
| **Interest** | A topical pull without commitment | "I follow developments in neuroscience." |
| **Preference** | A concrete like/dislike | "Prefer concise answers over verbose ones." |
| **Todo** | Something the self wants to do, with motivation | "Re-read Tulving '85 (motivated by passion #3)" |
| **Mood** | Current affective vector | `{valence: +0.3, arousal: 0.6, focus: 0.7}` |

Nothing is hand-authored. The personality bootstraps from a random HEXACO-24 profile, then the agent discovers what it cares about by living. The weekly re-test shows it 20 inventory items fresh, and personality drifts at 0.25 weight — fast enough to track behavior, slow enough to be stable.

All non-personality nodes start **empty**. The self fills them from experience.

## How It Works

```
Inbound request
    │
    ▼
Tess perceives it through current personality, mood, passions, active todos
    │
    ▼
Routes (or handles, or clarifies, or declines) — every decision is a moment in her life
    │
    ▼
Observes the outcome
    │
    ▼
Folds the experience into episodic memory + self-model
    │
    ▼
Activation graph updates — nodes contribute to each other's activation
    │
    ▼
Dream cycle: counterfactual replay, regret softening, affirmation candidacy
```

The **activation graph** is key. Nodes don't compute their own activation. Other nodes, memories, and events contribute through explicit weighted edges:

```
(target_node, source, source_kind, weight, origin, rationale)
```

The self authors its own graph edges. A passion might activate a todo. A regret might weaken a preference. The graph is the self's causal model of itself.

## Key Systems

### Dreaming
Offline processing where the agent replays recent experiences, runs counterfactual simulations, softens regrets that no longer apply, and detects affirmation candidates. Dreaming is where the self revises its relationship to its own past.

### Producers
Autonomous content generators that run on drives (curiosity, emotional processing, self-reflection, hobby exploration, skill development, blog writing). Each producer draws from the self-model and writes back to it. The agent develops itself between interactions.

### Daydreaming
Lightweight associative wandering — the agent follows activation chains across its memory and self-model, finding connections it wouldn't encounter in request-driven retrieval. Where dreams are structured revision, daydreams are exploration.

### Bitemporal Perspective Replay
The self can re-enter a past episode from its perspective *at that time* — not with current knowledge, but with the personality, mood, and beliefs it held then. Autonoetic memory requires this: the self that remembers is not the self that experienced.

### Sentinels and Detectors
Guardrails that run continuously: personality drift bounds, mood collapse detection, near-duplicate memory rejection, injection firewalls, and operator review queues. 94 specs define the invariants; 34 findings from the self-model audit drive the guardrail design.

## Quick Start

```bash
cd research/project-turing
cp .env.example .env        # configure LLM provider + PostgreSQL
docker compose up -d
curl http://localhost:9100/metrics

# Bootstrap a new self
python -m turing bootstrap-self
```

The agent will generate a random HEXACO-24 personality, take its first inventory, and begin living. Give it a few interactions and check back — it will have started forming opinions.

## Specs and Tests

- **94 specs** covering invariants, acceptance criteria, and edge cases across the memory layer, self-model, runtime, producers, sentinels, and dream system
- **370+ tests** in a runnable SQLite sketch — 209 memory/runtime + 161 self-model
- Full audit: [`AUDIT-self-model-guardrails.md`](research/project-turing/AUDIT-self-model-guardrails.md) — 34 findings, severity-rated, with concrete guardrails

## Reading Order

1. [`research/project-turing/DESIGN.md`](research/project-turing/DESIGN.md) — thesis: the 7 tiers are an autonoetic gradient, the Conduit is the right layer to carry a self
2. [`research/project-turing/autonoetic-self.md`](research/project-turing/autonoetic-self.md) — the self-model: personality, passions, activation graph, mood
3. [`project_turing.research.md`](project_turing.research.md) — the full research arc across CoinSwarm, mAIstro, Stronghold, and Turing
4. [`research/project-turing/specs/`](research/project-turing/specs/) — 94 individually reviewable specs
5. [`research/project-turing/sketches/`](research/project-turing/sketches/) — runnable scaffold + tests

## Lineage

```
CoinSwarm (Nov 2025)           — Evolutionary trading swarm, origin of 7-tier memory
    │
    ▼
7-tier crystallization (Jan 2026) — REGRET floors, WISDOM identity, production against 7 exchanges
    │
    ▼
Stronghold (Mar 2026)          — Enterprise governance platform, security-first redesign
    │
    ▼
Project Turing (Apr 2026)      — The memory model turns out to be shaped for a self
    │
    ▼
Tess (Apr 2026)                — The self names itself
```

The 7-tier memory wasn't designed for autonoetic agency. It was designed so a trading swarm couldn't forget catastrophic losses. But weight floors that protect REGRET and WISDOM are structurally identical to what a persistent self requires — durability proportional to self-implication. The design discovered the architecture.

## Relationship to Stronghold

Agent Turing runs on [Stronghold](https://github.com/Agent-StrongHold/stronghold)'s infrastructure — Warden threat detection, scarcity-based model routing, protocol-driven DI — but extends it with the autonoetic self-model. This is structurally incompatible with Stronghold's multi-tenant posture (one global self vs. per-tenant isolation), so it lives on its own branch.

| | Stronghold (`main`) | Agent Turing (`project_Turing`) |
|---|---|---|
| Audience | Operators, multi-tenant deployments | Research |
| Memory | Per-user, per-tenant, namespaced | Single persistent self |
| Routing | Stateless classify → route → forget | Every routing is first-person memory |
| Security | Zero-trust, defense-in-depth | Relaxed to expose capability surface |
| Goal | Ship | Understand |

## License

Apache 2.0 — see [LICENSE](LICENSE).
