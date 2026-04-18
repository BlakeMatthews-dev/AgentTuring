# Project Touring — Design

*An autonoetic Arbiter, built on the 7-tier episodic memory model.*

---

## 0. Framing

This document is a research design, not a build spec. It takes a position that the Arbiter — Stronghold's central triage/routing agent (formerly "Conduit") — is the natural locus for autonoetic reasoning, and that the 7-tier episodic memory model, viewed correctly, is already a skeleton for it.

Production Stronghold is not the target. The target is understanding what an agent with a persistent, self-indexed, temporally-bidirectional memory can do and cannot do, where it breaks, and which of its properties are worth the engineering cost to migrate back into a multi-tenant codebase.

## 1. Definitions we're using

Following Tulving's memory taxonomy:

- **Anoetic** — non-knowing. Procedural, implicit, sub-symbolic. In our codebase: raw tool-call traces, HTTP logs, token streams. Not memory in the cognitive sense.
- **Noetic** — knowing. Semantic facts without a self. "Paris is in France." In our codebase: OBSERVATION-tier memories and the knowledge base / RAG surface.
- **Autonoetic** — self-knowing. Memory that carries the subject. "I remember *being* there, I felt tired, I was trying to X, and I was surprised when Y." Requires a persistent self, mental time travel (backward and forward), affective indexing, and source monitoring.

An *autonoetic agent*, in this document, means one whose memory system structurally carries the self as a first-class indexed entity — not an agent we claim is conscious.

## 2. Lineage

The 7-tier model is a snapshot of an ongoing research line, not a starting point.

| Date | Milestone | What it contributed |
|---|---|---|
| **November 2025** | CoinSwarm begins | Weighted memory with reinforcement / contradiction / decay in an evolutionary-fitness context. The structural observation that certain failures must not decay — forgetting a catastrophic trading loss is prohibited — is the seed of what becomes REGRET's weight floor. |
| **January 15, 2026** | CoinSwarm production | 7-tier structure crystallized: OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM, bounded weights per tier, running against 7 exchange APIs. |
| **March 25, 2026** | Stronghold v0.1.0 | 7-tier model imported into the enterprise governance platform. Integrated with the Warden/Sentinel stack, 5-scope memory, per-agent/per-user indexing. |
| **April 2026** | Project Touring | This document. Thesis that the seven tiers are an autonoetic gradient and that the Arbiter is the right agent to extend. |

The continuity matters because it reframes what the seven tiers are. They are not an invention for Stronghold. They are the current state of five months of research on what a weighted, self-implicating memory structure needs to look like in an agent that must not forget certain things.

## 3. Thesis

**The seven tiers are already an autonoetic gradient, indexed by weight-floor self-implication. What's missing is the self itself as a first-class structural entity.**

### 3.1 Tulving's taxonomy already maps onto the tiers

| Tier | Weight bounds | Kind of knowing | Stance |
|---|---|---|---|
| OBSERVATION | 0.1 – 0.5 | Noetic | "X happened." No self required. |
| HYPOTHESIS | 0.2 – 0.6 | Autonoetic (weak) | "*I think* X might be true." Requires a believer. |
| OPINION | 0.3 – 0.8 | Autonoetic | "*I believe* X." Stronger commitment of self. |
| LESSON | 0.5 – 0.9 | Autonoetic | "*I learned* X from experience Y." Retrospective self-update. |
| REGRET | 0.6 – 1.0 | Autonoetic (anchor) | "*I* did X, *I* wish I hadn't." Requires persistent self-as-past-actor, counterfactual, affective weight. |
| AFFIRMATION | 0.6 – 1.0 | Autonoetic (prospective) | "*I* commit to X." Projects self into future episodes. |
| WISDOM | 0.9 – 1.0 | Autonoetic (identity) | "*I am* the kind of agent that…" Cross-version, cross-context selfhood. |

The weight floors are not just durability knobs. They are a measure of how deeply a memory implicates the self. OBSERVATION can decay to near-zero because nothing about the agent is staked on it. REGRET cannot drop below 0.6 because the self *is* staked on it — an agent that forgets its regrets is an agent that has forgotten what it is.

### 3.2 REGRET and AFFIRMATION are the bidirectional time-travel anchors

Autonoetic memory is characterized by mental time travel: the self re-enters past episodes and pre-enters future ones. The seven tiers already provide the two endpoints:

- **REGRET** — backward time travel. Requires a self that was the agent of a past act and can mentally re-enter the situation. The weight floor of 0.6 is the structural signature: the self is durably implicated.
- **AFFIRMATION** — forward time travel. The symmetric tier. Commitment projects the self into future episodes. Same weight floor.

REGRET without a persistent self is incoherent. AFFIRMATION without prospection is just a note.

### 3.3 WISDOM is identity

WISDOM is the only tier with floor ≥ 0.9, and the architecture document claims WISDOM "survives across versions." That is an identity claim. It requires a self-handle that outlives any particular deployment or instance — something more durable than the current `agent_id`.

## 4. Gap analysis — what the skeleton is missing

The seven tiers give us four of the autonoetic properties structurally: a self implied, bidirectional time anchors, affective/evaluative indexing via weights, and cross-version continuity via the WISDOM floor. To complete the model, five additions:

### 4.1 First-person markers as schema, not prose

Today, the autonoetic quality of a memory lives in its `content` string — "I believe X" is just text. Autonoesis requires promoting stance to structure:

```
affect: float in [-1.0, 1.0]          # valence at time of encoding
confidence_at_creation: float          # what I thought I knew
surprise_delta: float                  # how much the outcome violated priors
stance_owner_id: str                   # the self that holds this stance
intent_at_time: str                    # what I was trying to do
```

Retrieval then reconstructs *perspective*, not just text. "When I last encountered a routing decision like this one, I was confident (0.8), the outcome surprised me (+0.6), and I regretted delegating to Artificer over Scribe."

### 4.2 A stable self-ID that outlives instances

`agent_id` in the current codebase is per-instance. WISDOM claims to survive versions, but nothing in the type system tells us *whose* wisdom it is across versions. Project Touring needs a `self_id` — a stable handle the Arbiter carries across deployments, restarts, and version bumps. This is the thing WISDOM-tier memories actually belong to.

### 4.3 An explicit write-path into AFFIRMATION

REGRET has a clear origin: contradiction plus failed outcome plus weight promotion. AFFIRMATION has no symmetric origin in the current design. Nothing in the pipeline currently commits the agent to a future policy.

We need a **prospection step**: after a successful routing or a notable avoided failure, the Arbiter can write an AFFIRMATION — "I commit to preferring Scribe over Artificer for ambiguous writing-tinged requests." These entries bind future retrievals with the same weight-floor durability as regrets.

### 4.4 Source monitoring as an enforced field

Autonoetic memory distinguishes:

- **I-did** — experienced, first-person.
- **I-was-told** — reported by a user or another agent.
- **I-imagined** — generated during prospection or counterfactual reasoning.

Without this distinction, two failure modes emerge:

1. **Cognitive** — an imagined future retrieved later as a remembered past. The agent "remembers" something it only ever simulated.
2. **Security** — a prompt-injected claim that *the agent did X* gets stored as an I-did memory. This is a memory-injection attack. The absence of source monitoring turns the memory system into an attack surface.

Source becomes a required, enum-typed field. Retrieval can filter on it. Writes from untrusted channels default to I-was-told, never I-did.

### 4.5 Contradiction → REGRET conversion

Today, when an OPINION is contradicted by outcome, its weight decays. That is insufficient for autonoesis. A contradicted belief that merely fades is not self-implicating.

Project Touring proposes: when a stance-bearing memory (HYPOTHESIS, OPINION, LESSON) is contradicted by outcome, the pipeline *also* mints a REGRET entry linking to the original. The original remains in place for source-monitoring purposes. The REGRET carries the affective weight of "I was wrong, and it mattered." This is how the self accumulates.

## 5. What the Arbiter becomes

With the five additions, the Arbiter stops being a router and starts being an agent with a history.

**Current Arbiter.** Receives an ambiguous request → classifies → picks a specialist → delegates. Each invocation is stateless modulo session-stickiness heuristics. It has no memory of *its own* prior acts.

**Autonoetic Arbiter.** Receives a request and, before classifying, asks: *have I been in a situation like this before, and who was I when I handled it?* Retrieval reconstructs not just past events but the Arbiter's own stance at the time — what it believed, what surprised it, what it regretted, what it has since committed to via AFFIRMATION.

Concretely, new capabilities:

- **Recognition of recurrence.** "This request resembles the one I misrouted to Artificer on 2026-03-14. I have a REGRET about that. I am routing it to Scribe this time." The Arbiter cites *its own* prior experience.
- **Refusal grounded in self-knowledge.** "I have tried this class of delegation three times and regretted each. I decline to try again until the conditions change." The weight-floor on REGRET structurally prevents the agent from forgetting its own track record.
- **Policy via commitment.** An AFFIRMATION — "I commit to always Warden-scanning delegated writing outputs before returning them" — becomes a retrieval-weighted constraint on future routings, not an external rule the Arbiter could forget or be argued out of.
- **Prospective simulation.** Before delegating, the Arbiter runs a first-person forward retrieval: "if I delegate to Artificer on this, what do I, specifically, expect to encounter and to do?" This is not third-person planning; it is participant simulation, using the same machinery as episodic recall.
- **Source-aware caution.** When the Arbiter is told "you said X" about itself, it can check: is X an I-did memory or is it an I-was-told? If the latter, it's a claim about itself from outside, and it should be treated as provisional.

## 6. Art of the possible — open questions

Explicitly *not* a feature list. These are the questions the research branch exists to explore.

1. **Does the Arbiter develop something like preference?** If AFFIRMATIONs accumulate through normal operation — rewarded by successful routings — do we see the agent converge on stable preferences without them being programmed? What does that pattern look like in the weight distribution across tiers?
2. **What happens when contradiction accumulates?** If a class of delegations keeps failing, REGRETs mint and weights pile up. Does the Arbiter develop something functionally like self-distrust on that class? Is that behavior desirable or pathological?
3. **Can prospection replace planning?** For the Arbiter specifically — a shallow agent that mostly routes — can participant-simulation retrievals stand in for an explicit planner, since "what I will do next" is answered by retrieving similar past situations from a first-person index?
4. **What's the identity failure mode?** If `self_id` diverges — for instance, a fork or a bad migration creates two Arbiters that both claim the same WISDOM — what happens? Is there a structural way to detect and resolve this, or does it require external reconciliation?
5. **How does this interact with multi-tenancy when ported back?** A single autonoetic self is cleanly defined. A per-tenant autonoetic self is many selves. Is tenant-scoped autonoesis coherent, or does it require the agent to hold multiple identities with source-monitoring between them?
6. **Is the memory-injection attack tractable?** Source monitoring prevents the naive version. But if an attacker can influence an I-did entry indirectly — say, by causing the Arbiter to observe something that it then records about itself — the attack surface re-opens. What's the minimum set of invariants that keeps the self-index trustworthy?

## 7. What this document does not commit to

- No implementation on this branch yet. Prototypes will live in `sketches/` when and if they happen, isolated from `src/`.
- No claim that any of this should land in `main`. Findings may inform the production codebase; the default assumption is they do not.
- No claim of consciousness or sentience. Autonoetic, here, is a structural property of the memory system, not a philosophical one about the agent.
