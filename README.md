# Stronghold

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Security-first agent governance platform.** Every design decision in Stronghold starts with "how can this be exploited?" and works backward to function. It wraps any LLM in a zero-trust execution harness with defense-in-depth threat detection, intelligent model routing, self-improving memory, and protocol-driven extensibility.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

---

## Project Turing — Research Track

**→ Start here: [project_turing.research.md](project_turing.research.md)** — research arc across CoinSwarm, mAIstro, Stronghold, and Turing; the two principles the portfolio applies; and an honest read of where the Turing sketch breaks (with pointers to the 34-finding audit).

> **An autonoetic Conduit.** The central routing pipeline carries a persistent, self-indexed memory and routes from first-person experience — personality, mood, passions, skills, and todos — rather than stateless classification. One global self, no tenant scoping. Structurally incompatible with `main`'s multi-tenant posture; lives as a pseudo-fork on its own branch.

**Branches:** `project_Turing` (integration / "main" of the pseudo-fork) · `research/project-turing` (active research) · `claude/autonoetic-self-tranche-6` (example feature branch) — feature work flows `feature → research/project-turing → project_Turing → main`.

**What it is:**
- A near-fork experiment that promotes the Conduit from noetic router (classify → route → forget) into an autonoetic reasoning layer (remembers its own prior routings as first-person experience, projects itself into future routings, can regret, can commit).
- A 7-tier episodic memory (OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM) extended with a self-model: HEXACO-24 personality with weekly re-test, passions / hobbies / interests / skills (with decay) / preferences, mood vector, self-authored todos with required provenance, and an activation graph whose edges the self itself authors.
- 30 specs covering invariants, acceptance criteria, and edge cases; a runnable SQLite sketch with 370 green tests (209 memory/runtime + 161 self-model).

**What it is not:** a roadmap item, a competitor to the enterprise codebase, or a claim that any of this is production-ready. Findings may or may not feed back to `main`; if anything works, it gets redesigned for multi-tenancy before landing in `src/`.

**Reading order:**
1. [`research/project-turing/DESIGN.md`](research/project-turing/DESIGN.md) — thesis, Tulving-taxonomy mapping, what the Conduit becomes when it has a self.
2. [`research/project-turing/autonoetic-self.md`](research/project-turing/autonoetic-self.md) — the content of the self the Conduit carries.
3. [`research/project-turing/specs/`](research/project-turing/specs/) — 30 individually reviewable specs, read in order.
4. [`research/project-turing/sketches/`](research/project-turing/sketches/) — runnable scaffold + tests.

**Lineage:** CoinSwarm (Nov 2025) → 7-tier crystallization (Jan 15, 2026) → Stronghold import (Mar 25, 2026) → Project Turing (Apr 2026).

---

## Origin

**Project Maistro** (a.k.a. Conductor, Feb 19, 2026 – present) is a parallel project — a more secure implementation of the autonomous agent harness popularized by OpenClaw. Maistro proved the core concepts: routing, memory, multi-agent orchestration, and functional security. It remains an active project.

**Stronghold is a complete redesign**, not a port. Built from the learnings of Maistro and Conductor, Stronghold was designed from first principles with security as the unitary architectural foundation. Maistro was *security and function*. Stronghold is **security-first design, then function** — every architectural decision is derived from the security model, not constrained by it after the fact.

The initial commit (March 25, 2026) established the security-first architecture with 481 files — the Warden/Gate/Sentinel stack, 6-agent roster, scarcity-based model routing, and self-improving memory — informed by Maistro's and Conductor's battle-tested patterns but redesigned for zero-trust from the ground up.

## Timeline

| Date | Milestone |
|---|---|
| **Jan 15** | **CoinSwarm** — biological-evolution-inspired hybrid micro-agent + statistical engine swarm for crypto/equities trading. Evolutionary fitness loops, ELO scoring, trio voting, memory reinforcement/contradiction/decay. Origin of the 7-tier episodic memory model. Production system against 7 exchange APIs. |
| **Feb 19** | **Project Maistro** begins — autonomous agent harness with routing, memory, multi-agent orchestration (parallel project, still active) |
| **Mar 25** | **Stronghold v0.1.0** — complete redesign from Maistro/Conductor learnings. Security-first architecture, 481 files. 4-layer Warden, Gate, Sentinel, 6-agent roster, scarcity routing, 7-tier memory, 203 unique attack payloads in test suite. |
| Apr 1 | Frank + Mason builder pipeline, deterministic strategies, issue-driven feedback loops |
| Apr 2 | Builders 2.0 — unified agent architecture, learning strategy with repo recon and self-diagnosis |
| Apr 6–9 | CI hardening, ruff cleanup, lint/type strictness across all modules |
| Apr 12 | 95% test coverage — 550+ tests, 6 bug fixes |
| **Apr 16** | Feature comparison; RASO direction shift influenced by [Hyperagents](https://arxiv.org/abs/2603.19461) paper |
| **Apr 18** | Spec-driven verification system — Spec type, pipeline wiring, property-test gen, planner triage, Quartermaster + Archie agents |

## Changelog

Major methodology and architectural shifts. For feature milestones see Timeline above; detailed rationale for each entry lives in the linked document.

| Date | Shift | Why |
|---|---|---|
| **2026-04-17** | **Branch model simplified from 4 tiers to 3**: `feature/* → integration → main`. `develop` retired. | `develop` went stale (5 days, superseded by `1a82c48` merge to main). No open PRs targeted it. Collapsing the dev-join tier is free — Mason PRs are already atomic units per-issue; there's nothing to congregate before the QA gate. Integration remains as the heavy-test / QA tier. Feature branches now base off `integration`. |
| **2026-04-17** | **Spec-driven development adopted as the primary methodology for autonomous test generation.** Archie's output becomes `Spec + ACs` (not `List[AC]`); Mason implements against the Spec; Auditor validates tests against Spec contracts rather than checking pytest-green. See [docs/test-quality-audit-and-ci-gate-proposal.md](docs/test-quality-audit-and-ci-gate-proposal.md). | Audit of 3,775 tests found 8.8% vanity assertions suite-wide; AC-driven Mason tests were 60-90% weak or tautological in the pre-audit sample. The 7 spec-driven modules hit 99.4% coverage with zero WEAK or BAD classifications. **Pre/post: coverage 94% → 95%, tests 3,833 → 3,933, failures 13 → 0, flagged-pattern occurrences (`hasattr` / `call_count` / `inspect.getsource` / status-tolerant / bare `isinstance`) 258 → 0, WEAK+BAD tests remaining: none detected by audit criteria.** Specs are the load-bearing fix; CI gates below are the safety net. |
| **2026-04-17** | **Assertion-strength CI gates** proposed for the `feature/* → integration` merge path. Three stages, rolled out progressively: **(1)** AST pattern linter (status-tolerance, `isinstance`-after-construction, no-assert tests); **(2)** LLM assertion judge seeded with this PR's 3,775-example catalog; **(3)** targeted mutation testing on changed src files (opt-in per PR diff, `mutmut` as the engine). Blocks on `BAD`, warns on `WEAK`, runs between Auditor and Gatekeeper in the agent pipeline. | Auditor currently validates test *presence* and pytest-green, not assertion strength. Gates catch the over-tolerant-status, BDD-comment-mismatch, and AC-wording-duplication patterns that slip past Auditor today without requiring Mason prompt changes. |
| **2026-04-18** | **Spec-driven verification system implemented end-to-end.** `Spec` type (invariants, acceptance criteria, property tests) flows through the builder pipeline: Quartermaster emits → Archie enriches with Hypothesis property tests → Mason implements against → Auditor gates on `SPEC_COVERAGE_GAP`. `InvariantVerifier` checks coverage; `SpecTemplateStore` enables plan reuse across similar issues. Prompt caching via `inject_cache_breakpoints()` marks stable system prompts with `cache_control`. Complexity-based planner triage routes simple issues to Sonnet, reserves Opus for complex. Nine YAML specs in `specs/` bootstrap the pattern on itself. | The Apr 17 audit identified spec-driven modules as the highest-quality test output (99.4% coverage, zero weak/bad). This commit operationalizes that finding: specs become a runtime data structure flowing through the pipeline, not just a methodology. Quartermaster and Archie agents (P4/P5 tiers) formalize the planning and scaffolding stages. Property tests derived from invariants via Hypothesis replace hand-written edge cases for spec-governed modules. **Pre/post: tests 3,854 → 3,897, new modules 12, property tests 35+, YAML specs 9.** |
| **2026-04-18** | **CI-debt closeout — 5 quality/security gates wired as blocking**: Xenon (complexity, rank C max), Vulture (dead code, min-confidence 100 + whitelist), Semgrep (SAST, p/flask + p/secrets + p/python), Gitleaks (secret-scan, doc-fixture allowlist), Hadolint (Dockerfile). Joins the existing Bandit + pip-audit + CodeQL + Ruff + Mypy-strict gates. Closes #1026 (epic) plus 7 child issues. See [COMPARISON.md §9](COMPARISON.md#9-ci--quality-gates) for the per-tool comparison against industry baselines. | The epic tracked 10 failing jobs from the self-hosted runner rollout. Root causes ranged from real bugs (helm vault nil pointer, Flask format-string vuln, 5 logger-credential-disclosures Semgrep caught that Bandit missed) to tool-config gaps (missing Gitleaks allowlist, missing Vulture whitelist for decorator-indirection). Shipping the gates wired + the findings fixed in one PR keeps the comparison table honest — we claim blocking gates only when they're actually blocking. |

## Quick Start

```bash
docker compose up -d
curl http://localhost:8100/health
```

## Feature Comparison

How Stronghold compares to other agent frameworks and platforms. Stronghold is an opinionated governance platform — not just an orchestration library or a coding agent — so some comparisons are apples-to-oranges by design.

**Legend:** ✅ = Implemented&ensp; 🟡 = Partial / requires integration&ensp; 🗺️ = Roadmapped&ensp; ❌ = No competitor offers this

> Full feature-by-feature breakdown with detailed analysis: **[COMPARISON.md](COMPARISON.md)**

| Feature | Stronghold | Closest Competitor | Gap |
|---|:---:|---|---|
| **Architecture & Deployment** | | | |
| Open source (Apache 2.0) | ✅ | Most frameworks (MIT) | Archestra is AGPL-3.0; Hyperagents CC BY-NC-SA |
| Self-hosted + K8s native | ✅ | MS Agent Framework, Archestra | Both also ship Helm charts; most others are library-only |
| Protocol-driven DI (20 protocols) | ✅ | MS Agent Framework | Only other framework with pluggable protocol interfaces |
| **Multi-Agent Orchestration** | | | |
| Shipped agent roster (6 agents) | ✅ | ❌ | No framework ships production-ready specialist agents |
| 4 reasoning strategies + custom | ✅ | LangGraph, CrewAI | Graph nodes (LangGraph) and process types (CrewAI) are comparable |
| Intent classification (keyword + LLM) | ✅ | LangGraph 🟡 | LangGraph supports conditional routing but no built-in classifier |
| Multi-intent parallel dispatch | ✅ | MS Agent Framework, LangGraph, CrewAI | All support parallel execution; none have built-in intent splitting |
| Tournament-based agent evolution | 🟡 | ❌ | Scaffolding implemented (Elo scoring, battle recording); not yet wired to production routing (v1.1) |
| Dynamic intent creation | ✅ | ❌ | Unique to Stronghold |
| Proactive behavior (Reactor) | ✅ | OpenClaw 🟡 | OpenClaw has basic cron; no framework has a 1000Hz event-driven reactor |
| GitAgent import/export | ✅ | ❌ | Unique to Stronghold |
| **Security & Governance** | | | |
| Input scanning (Warden) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra | All four scan user input; approaches differ (regex+LLM vs guardrails vs dual-LLM) |
| Tool result scanning (Warden) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra | Stronghold + these three are the only ones scanning tool results |
| Output scanning (Sentinel) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra, Claude Code | Claude Code uses OS-level sandboxing rather than content scanning |
| Trust tiers (☠️→T0) | ✅ | MS Agent Framework | 5 tiers with tier-based access control. Auto-promotion gates roadmapped (v1.1); currently manual. |
| Schema validation & repair | ✅ | OpenAI Agents SDK | OpenAI uses Pydantic validation; Stronghold adds fuzzy repair of hallucinated args |
| PII filtering | ✅ | MS Agent Framework, Archestra | All three scan outbound responses |
| Config-driven RBAC | ✅ | MS Agent Framework, Archestra | MS uses Entra ID; Archestra uses org/team scoping; Stronghold supports both Keycloak + Entra |
| Per-agent tool permissions | ✅ | MS Agent Framework, Archestra, CrewAI | Stronghold enforces via LiteLLM per-key config |
| Rate limiting | ✅ | MS Agent Framework, Archestra | All three enforce at the gateway level |
| Zero-trust architecture | ✅ | MS Agent Framework 🟡, Archestra 🟡 | Stronghold scans all three boundaries (input, tool-result, output); MS and Archestra have partial zero-trust |
| **Memory & Learning** | | | |
| 7-tier episodic memory | ✅ | ❌ | Unique to Stronghold — regrets (≥0.6) structurally unforgettable |
| Self-improving learnings (fail→succeed) | ✅ | Hyperagents ✅, Claude Code 🟡 | Hyperagents: research-only metacognitive loop; Claude Code: static auto-memory |
| 5 memory scopes (global→session) | ✅ | MS Agent Framework 🟡 | MS has pluggable memory backends but not 5-level scoped retrieval |
| Memory decay & reinforcement | ✅ | ❌ | Unique to Stronghold |
| Auto-promotion of corrections | ✅ | ❌ | Unique to Stronghold |
| Knowledge/RAG (pgvector) | ✅ | MS Agent Framework | Both have built-in vector retrieval |
| RASO (self-modifying agent graph) | 🗺️ v1.2–1.3 | Hyperagents (research) | Inner feedback loop shipped. Meta-agent roadmapped v1.2 (Phase 1) → v1.3 (Phase 2). |
| **Model Routing** | | | |
| Intelligent cost/quality routing | ✅ | Archestra | Archestra uses a dynamic optimizer (up to 96% cost reduction); Stronghold uses scarcity-based scoring |
| Automatic fallback (429/5xx) | ✅ | MS Agent Framework, Archestra, Pi | All four handle provider failures with automatic model fallback |
| Task-type speed bonuses | ✅ | ❌ | Unique to Stronghold — voice gets speed weight, code gets quality weight |
| Token budget enforcement | ✅ | MS Agent Framework, Archestra, Pi | All four enforce per-request token budgets |
| **Tool Ecosystem** | | | |
| MCP support | ✅ | Claude Code, OpenAI Agents SDK, MS Agent Framework, Archestra | Stronghold via LiteLLM gateway; Archestra has 858+ server registry |
| AI tool/agent creation (Forge) | 🟡 | ❌ | Generate → security scan → save implemented. Test→iterate loop roadmapped (v1.2). |
| OpenAPI auto-conversion | ✅ | MS Agent Framework | Both auto-convert OpenAPI specs to callable tools |
| Skill marketplace | ✅ | Archestra, MS Agent Framework, OpenClaw | Archestra has largest catalog (858+ servers) |
| **Observability** | | | |
| OTEL tracing | ✅ | MS Agent Framework, OpenAI Agents SDK, LangGraph | All use OTEL; Stronghold routes to Arize Phoenix |
| Prompt management (PostgreSQL) | ✅ | LangGraph 🟡 | LangGraph uses LangSmith (SaaS); Stronghold uses self-hosted PostgreSQL |
| Cost tracking | ✅ | MS Agent Framework, Archestra, Pi | All four track per-request costs |
| **Enterprise & Multi-Tenant** | | | |
| SSO / OIDC | ✅ | MS Agent Framework, LangGraph Platform | Stronghold supports both Keycloak and Entra ID |
| Multi-tenant isolation | 🗺️ v1.3 | MS Agent Framework, Archestra, LangGraph Platform | All three have production multi-tenancy today |
| Namespace-scoped secrets | 🗺️ v1.3 | MS Agent Framework, Archestra | Both have per-tenant secret management |
| Agent marketplace | 🗺️ v1.3 | MS Agent Framework, Archestra | Both have agent/tool registries |
| **CI & Quality Gates** | | | |
| Security gates (Bandit + Semgrep + pip-audit + Gitleaks + Hadolint + CodeQL) | ✅ all blocking | Most ship dependabot + 1-2 SAST | Full 5+1 blocking is uncommon in OSS; matches OWASP ASVS L2 baseline |
| Code quality gates (Ruff + Mypy-strict + Xenon + Vulture) | ✅ blocking | Ruff + Mypy typical | Xenon (complexity) and Vulture (dead code) rare in OSS; typical only in regulated sectors |
| Tiered coverage gates (85% feature / 90% integration / 95% main diff) | ✅ | Industry avg ~75% flat ([Hilton 2016](https://cmhilton.com/papers/hilton-msr-2016-coverage.pdf)) | Tiered-by-merge-target uncommon; 95% diff on main matches regulated-sector bar |
| Assertion-strength gate (AST linter → LLM judge → mutation) | 🗺️ staged | ❌ | Unique — no framework gates assertion quality; [Petrovic 2018](https://research.google/pubs/state-of-mutation-testing-at-google/) shows mutation testing rare even at Google |

### What Makes Stronghold Different

Most agent frameworks give you **building blocks** (LangGraph, OpenAI Agents SDK) or a **finished product** (Claude Code, OpenClaw). Stronghold is an **opinionated governance platform** — it ships with a complete agent roster, security scanning at every trust boundary, self-improving memory, and intelligent model routing, all behind swappable protocol interfaces.

**Unique among shipping frameworks** (no other framework implements these):
- **Three-boundary security scanning** — Warden scans both user input *and* tool results before they enter LLM context. Sentinel scans output before it reaches the user. Most frameworks scan input only; Stronghold scans all three trust boundaries.
- **7-tier episodic memory with structural weight floors** — Regrets (≥0.6) are structurally unforgettable. Wisdom (≥0.9) is near-permanent. Originated in CoinSwarm (a trading swarm where forgetting catastrophic losses is prohibited). No other framework has tiered memory with enforced decay bounds.
- **Self-improving learnings with auto-promotion** — Extracts fail→succeed corrections from tool-call history, stores with trigger keywords, auto-promotes to permanent prompt after N successful injections, bridges to episodic memory. No other framework combines extraction + promotion + episodic bridge.
- **Scarcity-based model routing** — `cost = 1/ln(remaining_daily_tokens)`. Cost rises smoothly as provider token pools deplete. No comparable formula found in frameworks or in our literature review. Archestra has a dynamic optimizer but uses a different approach.
- **Tournament-based agent evolution** — Elo scoring and battle recording implemented (production wiring in v1.1). Pattern originated in CoinSwarm (January 2026, 3 weeks before EvoMAS). No other framework has this.
- **1000Hz Reactor** — Deterministic tick loop (inspired by game loop architecture) that unifies all proactive behavior into one evaluation cycle. The design choice is driven by security: in async fire-and-forget, a hanging thread or a missing callback can silently become a positive result — an agent proceeds because it didn't hear "no." In agent security, no answer must be a failure mode, not a pass. A deterministic loop guarantees consistent evaluation ordering, no race conditions, and no silent timeouts that an agent misinterprets as approval. The broader design principle: maximize determinism everywhere between LLM calls. The LLM is the minimally required non-deterministic element — everything else (routing, scanning, policy enforcement, trigger evaluation) is deterministic by design. Four typed trigger modes (event, interval, time, state), per-trigger circuit breakers, blocking gates (≤1ms). The starting design comp was OpenClaw, where the agent brain evaluates on a 15-minute heartbeat. The Reactor evaluates at 1000Hz — a 900,000x improvement in evaluation frequency for 0.46% of one logical core on a 4-generation-old 13th gen Intel. Not because agents need to act 1,000 times per second, but because the system should never be waiting 15 minutes to discover that something needs attention. No comparable system found in frameworks or in our literature review.

**Unique among shipping frameworks, with comparable research** (published in papers but not implemented in any framework):
- **5-tier earned trust** — ☠️ → T3 → T2 → T1 → T0 with tier-based access control. Auto-promotion gates roadmapped (v1.1); currently manual. MS Agent Framework has trust tiers. Governance Architecture paper (arXiv:2603.07191) describes a comparable framework.
- **Memory decay & reinforcement** — Memories weaken without reinforcement, strengthen with use. Adaptive Memory Admission Control (arXiv:2603.04549) describes comparable mechanisms. Stronghold shipped it first (via CoinSwarm, January 2026).
- **Protocol-driven DI with zero direct external imports** — 20 protocols, 32+ Protocol classes. Business logic depends only on protocols. Standard software engineering pattern but no other agent framework applies it at this scale.

**Roadmapped** (inner loop shipped, meta-layer planned):
- **RASO (v1.2–v1.3)** — Reflexive Agentic Self-Optimization. The Auditor→Mason feedback cycle is shipped and functional. The meta-agent that modifies the graph structure itself is roadmapped. Meta FAIR's Hyperagents paper describes the theoretical construct; Stronghold's inner feedback loop predates it (CoinSwarm January 2026, Maistro February 2026), but the self-referential framing was influenced by the paper after discovery on April 16.
- **Forge iteration loop (v1.2)** — Currently generate→scan→save. Test→iterate loop with sample/adversarial inputs planned.
- **Multi-tenant isolation (v1.3)** — K8s namespace-per-tenant, scoped secrets, agent marketplace.

**Roadmap — Reflexive Agentic Self-Optimization (RASO):** Stronghold's builders loop implements plan → execute → review → learn → iterate with automatic learning extraction and correction promotion. The underlying concept — agents improving via structured feedback from other agents — traces back to CoinSwarm's evolutionary fitness loops (January 2026, where agent populations self-improve through evaluation pressure, memory reinforcement, and trait inheritance) and Maistro's trace reviewer (February 2026, where an agent reviews another agent's execution traces and produces structured corrections). Stronghold's feedback module (April 2, 2026) was developed independently of Meta's [Hyperagents](https://arxiv.org/abs/2603.19461) paper (published March 19, 2026; discovered April 16, 2026). The RASO roadmap — wrapping a meta-agent around the builders graph so it can modify its own structure — was influenced by HyperAgents after discovery. Previously called "naive RLHF" internally; renamed because the feedback is primarily agent-driven (tournaments, learning extraction, quality gates), with optional human feedback via PR comments. *Direction shifted April 16, 2026 based on influence of Hyperagents paper.*

## License

Apache 2.0 — see [LICENSE](LICENSE).
