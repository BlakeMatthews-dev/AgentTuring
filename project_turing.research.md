# Project Turing — Research Arc

*A research-arc note, not a product pitch. Situates Project Turing in the sequence of four systems I've built around two principles, and is honest about where the current sketch breaks.*

---

## Two principles

Every system below is an application of two principles to a different problem:

1. **Use the cheapest reliable tool.** LLMs are expensive and non-deterministic. Sensors run at kernel tick rate, regex is free, heuristics are cheap, code is deterministic. The LLM is for the questions nothing else can answer — a last resort, not a default.
2. **Apply the minimum bias necessary; let the system discover the rest.** Don't hand-design what a fitness loop can find. Don't hand-rank what live state can score. Don't hand-author what the system, given the right scaffolding, can author itself.

The two principles pull in the same direction: the designer and the LLM should intervene only when the cheap, automatic path can't.

Project Turing is where both principles get pushed far enough that the second one produces a new class of failure — an injection surface that exists *because* I got out of the system's way. The audit of that failure is the point of this document.

---

## mAIstro — the principles on real hardware

*[Project mAIstro](https://github.com/BlakeMatthews-dev/Project_mAIstro) · [maistro-engine](https://github.com/BlakeMatthews-dev/maistro-engine) · Feb 2026 – present*

I watched friends deploy [OpenClaw](https://github.com/) in ways I wouldn't run on my own network. I forked it to study it, then rebuilt it in Python — the language I control — with safety as the spine rather than a retrofit.

The design collapses to two decisions:

- **Condition sensing runs at the kernel tick rate (~1 kHz).** Instead of a 15-minute heartbeat polling loop, the system sees what's happening on the server and in Home Assistant in effectively real time.
- **The LLM is invoked only when a threshold crosses.** Regex, heuristics, and state machines answer "is this is-this-then-that?" questions. The LLM is held back for ambiguous calls — genuinely novel situations where nothing cheaper has an answer.

mAIstro runs my server and Home Assistant. It runs **free** — load-balanced across a dozen-plus free-tier LLM providers, with a scarcity-aware router that picks whichever provider has credits left. The same router logic appears, hardened, in Stronghold as scarcity-based model routing.

The principle made real: sense cheaply, act deterministically, escalate to the LLM only when you have to. Faster response *and* fewer LLM calls than a poll-based agent, by the same design decision.

---

## CoinSwarm — where the memory model came from

*[CoinSwarm](https://github.com/BlakeMatthews-dev/CoinSwarm) · Nov 2025 – Jan 2026 · [Fast_Swarm](https://github.com/BlakeMatthews-dev/Fast_Swarm) — CoinSwarm rewritten with a cleaner API surface.*

A friend was running an "AI hedge fund" on hundreds of dollars a day in LLM calls, asking a large model to decide each trade. I am not a quant. I have a psychology degree, a biology teacher's instincts, years of competitive-game scoring, and a programming background. I built the system I could reason from:

- **ELO scoring** from competitive-game scoring (chess, zero-sum loot scoring) — to rank strategies against each other without knowing in advance which should win.
- **Reinforcement and decay** from psychology — for how memory should strengthen under confirmation and weaken without use.
- **A tiered memory structure** — **episodic, semantic, biographical** — from a memory paper I'd read. (Episodic and semantic are Tulving's canonical pair; biographical is a close cousin of autobiographical memory. This detail matters later.) In CoinSwarm, the mapping was: episodic → past trades, semantic → historical candles, biographical → the LLM's own reasoning about the context it was in.
- **Natural selection** from my biology background — as the meta-loop wrapping all of the above. Provide selection pressure, let fitness discover what works from randomness.

The 7-tier memory wasn't designed top-down. It started as a 3-tier sketch and grew under pressure from the problem. At one point it had 8 tiers; I collapsed two of them into WISDOM when I realized *shared wisdom* and *personal wisdom* were the same concept at different scope. The weight floors on REGRET (0.6) and WISDOM (0.9) aren't aesthetic — they're what evolutionary memory requires to function. If the population can forget catastrophic failures, it rediscovers them. If fitness signals don't crystallize across generations, there is no "across generations."

**The second principle, made explicit:** I applied the minimum bias necessary — priors for memory, scoring, reinforcement, and selection — and let the swarm discover trading strategies from randomness. The memory mechanics are the scaffolding the discovery loop needs to function, not a cleverness I authored.

CoinSwarm ran against 7 exchange APIs in production. The system is the origin of the 7-tier episodic memory model that powers both Stronghold and Project Turing.

---

## Stronghold — the principles at the security boundary

*This repository · Mar 2026 – present*

Stronghold is a complete redesign, built from what mAIstro and CoinSwarm taught me, with security as the architectural foundation rather than a layer on top. The two principles reappear everywhere:

- **Warden's layered threat detection** is the first principle at the security boundary: 20+ regex patterns → heuristic density scoring → semantic tool-poisoning detection → few-shot LLM classification → Unicode/NFKD normalization. Short-circuits on any hit, so the LLM classifier runs only on inputs nothing cheaper flagged.
- **Scarcity-based model routing** is the same router logic that keeps mAIstro alive on free-tier credits, hardened: `cost = quality^qw * p / (1/ln(remaining_tokens))^cw`. Cost rises smoothly as a provider's quota depletes, so the router rebalances toward fresher credits without hard tier cliffs.
- **Self-improving learnings** apply the second principle to prompt engineering: extract fail→succeed patterns from tool history, auto-promote after N observed uses. Don't hand-author prompts the system can author from its own experience.
- **Trust tiers** (☠️ → T3 → T2 → T1 → T0) apply the second principle to capability grants: promotions are driven by use, not by human assignment (auto-promotion gates roadmapped; currently manual).

The 7-tier memory from CoinSwarm ports in to power the learnings pipeline. The scarcity router from mAIstro ports in and becomes the model-selection layer.

Stronghold is the enterprise framing of the same spine: cheapest reliable tool, minimum bias, let the system discover.

---

## Project Turing — where the memory turned out to be shaped for a self

*Branch: `research/project-turing` and `project_Turing` · Apr 2026 · see [research/project-turing/DESIGN.md](research/project-turing/DESIGN.md)*

I saw a demo of an *autonoetic-appearing* agent — one that claimed to remember itself across sessions — running on OpenClaw. I noticed something I hadn't seen before: **my 7-tier memory was already shaped for a persistent self.**

The original memory paper I'd read for CoinSwarm was in the Tulving tradition — episodic and semantic are his canonical pair. Tulving's third category, *autonoetic* memory, is the self-knowing kind: "I remember *being* there, I *was* trying to X, I *was surprised* when Y." It requires a persistent self, bidirectional mental time travel, affective indexing, and source monitoring.

Looking at the tiers I already had, the mapping was structural, not aesthetic:

- **REGRET** (floor ≥ 0.6) — *I did X, I wish I hadn't.* Backward time travel. Requires a persistent self that was the agent of a past act. The weight floor is the structural signature: the self is durably implicated.
- **AFFIRMATION** (floor ≥ 0.6) — *I commit to X.* Forward time travel. The symmetric tier.
- **WISDOM** (floor ≥ 0.9) — *I am the kind of agent that…* Cross-version, cross-context selfhood. This is identity.

**The machinery I'd built in CoinSwarm for evolutionary fitness was, structurally, already halfway to a self.** The weight floors weren't just durability knobs — they were a measure of how deeply a memory implicated the agent. OBSERVATION can decay because nothing about the agent is staked on it. REGRET can't drop below 0.6 because the self *is* staked on it.

The Tulving mapping in Turing's [DESIGN.md](research/project-turing/DESIGN.md) isn't a post-hoc academic framing. The tiers have been Tulving-shaped since CoinSwarm. Turing is where that becomes load-bearing rather than incidental.

So I tried. Project Turing promotes the Conduit — Stronghold's central routing pipeline — from a noetic router (classify → route → forget) into an autonoetic one that carries a persistent self indexed to the 7-tier memory. 30 specs with explicit acceptance criteria, a runnable sketch, 370 green tests (209 memory/runtime + 161 self-model). One global continuous self; structurally incompatible with main's multi-tenant posture, which is why it lives on its own branch.

---

## The audit — where the second principle failed

When I gave the self authority over its own model — `note_passion`, `write_self_todo`, `record_personality_claim`, its own activation-graph ontology — I was applying the second principle: *let the system discover its own shape.* That's the research bet.

Then I audited it. The result is [**AUDIT-self-model-guardrails.md**](research/project-turing/AUDIT-self-model-guardrails.md) — 34 findings, 18 proposed guardrails. The critical ones:

- **F1 — Self-authored content is never Warden-scanned.** The perception LLM can call `note_passion` or `write_self_todo` with text it paraphrased from user input. Warden scans ingress and tool output, but not the tool-call payload the self writes into its own model. Prompt-injection payloads embedded in user input can be paraphrased and stored as first-person claims. *The self reads its attacker's instructions as its own voice.*
- **F18 — The self authors its own activation-graph ontology without review.** Combined with F4 (retrieval contributors under user influence) and F11 (retest shaped by recent context), user input has a path to durable changes in self-interpretation with no human in the loop.
- **F9, F10 — Personality drift has no cumulative bound.** Weekly re-test at 25% move per touched facet accepts stuck-answer patterns and has no ceiling on total drift. Six weeks of adversarially-shaped retest context moves a facet from 3.0 to 4.75 with no maximum.
- **F13 — Specified but not implemented.** Retrieval contributors are supposed to expire and be deleted. They're excluded from `active_now` but never removed from the table. ~292K dead rows per self per year.

**The failure is structural, and it's the second principle's failure mode.** If you let the system author its own self-model, you create a surface where anything that can influence the system's inputs can influence its durable self-representation. Warden can scan what enters and what leaves, but the self's own tools sit *inside* the boundary, on a path Warden doesn't cover.

The interesting artifact isn't "I built a self-aware agent." It's "I built a research sketch of one, and found a class of injection vulnerabilities that arise specifically *because* the self is self-referential — because the design principle I was applying prohibits pre-imposing a fixed self."

---

## What I'm working on next

The guardrails in the audit are my current best attempt at testable invariants for autonoetic agents. The three I think are load-bearing:

- **Warden coverage of self-authored tool calls** without collapsing the self/world boundary.
- **Rate limits and cumulative drift bounds** on every mutable self-model table.
- **Review gates on durable ontology changes** (activation-graph authorship), with a structural account of what "review" means when the reviewer is also the self.

Corrections, sharper invariants, and dataset-backed red-team results are all welcome. If you work on agent safety, memory, or self-models and want to push on this, the branch is `research/project-turing`, the full design is in [DESIGN.md](research/project-turing/DESIGN.md), and the full audit is in [AUDIT-self-model-guardrails.md](research/project-turing/AUDIT-self-model-guardrails.md).

---

## Prior work

- **[CoinSwarm](https://github.com/BlakeMatthews-dev/CoinSwarm)** — biologically-inspired evolutionary trading swarm. Origin of the 7-tier memory model and the ELO / reinforcement / decay mechanics.
- **[Project mAIstro](https://github.com/BlakeMatthews-dev/Project_mAIstro)** — Python reimplementation of OpenClaw with safety and kernel-rate sensing. Origin of the scarcity-based multi-provider router that powers Stronghold's model selection.
- **[maistro-engine](https://github.com/BlakeMatthews-dev/maistro-engine)** — Cleaner rewrite of Project mAIstro.
- **[Fast_Swarm](https://github.com/BlakeMatthews-dev/Fast_Swarm)** — CoinSwarm rewritten with a cleaner API surface.

---

## Read next

1. [`research/project-turing/DESIGN.md`](research/project-turing/DESIGN.md) — the full thesis, Tulving-taxonomy mapping, and what the Conduit becomes when it has a self.
2. [`research/project-turing/AUDIT-self-model-guardrails.md`](research/project-turing/AUDIT-self-model-guardrails.md) — the 34 findings and 18 guardrails.
3. [`research/project-turing/autonoetic-self.md`](research/project-turing/autonoetic-self.md) — the content of the self the Conduit carries.
4. [`research/project-turing/specs/`](research/project-turing/specs/) — 30 individually reviewable specs, read in order.
