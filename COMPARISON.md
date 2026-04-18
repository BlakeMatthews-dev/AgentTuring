# Feature Comparison — Detailed Analysis

How Stronghold compares to 10 agent frameworks and platforms across 8 categories.

**Compared frameworks:**

| Framework | Type | License | What It Is |
|---|---|---|---|
| [Claude Code](https://claude.ai/code) | Coding agent | Source-available | Anthropic's agentic coding tool with OS-level sandboxing |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Agent SDK | MIT | Production SDK with guardrails, handoffs, and tracing |
| [MS Agent Framework](https://github.com/microsoft/agents) | Enterprise framework | MIT | Microsoft's Semantic Kernel + AutoGen successor, Azure-native |
| [Archestra](https://archestra.ai) | MCP orchestration | AGPL-3.0 | Enterprise MCP gateway with dual-LLM security and K8s runtime |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Orchestration library | MIT | Stateful multi-agent graphs with checkpointing (LangChain) |
| [CrewAI](https://github.com/crewAIInc/crewAI) | Multi-agent framework | MIT | Role-based agent crews with process orchestration |
| [OpenClaw](https://github.com/openclaw/openclaw) | Personal assistant | MIT | 24/7 autonomous agent on your hardware via messaging platforms |
| [Hyperagents](https://arxiv.org/abs/2603.19461) | Research | CC BY-NC-SA | Meta's self-referential self-improving agents (non-commercial) |
| [Deep Agents](https://github.com/langchain-ai/deep-agents) | Agent harness | MIT | Opinionated LangGraph-based coding agent harness |
| [Pi](https://github.com/badlogic/pi) | Agent toolkit | MIT | TypeScript monorepo powering OpenClaw's runtime |

**Legend:** ✅ = Full support | 🟡 = Partial / requires integration | 🗺️ = Roadmapped | ❌ = Not available

---

## 1. Architecture & Deployment

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Open source | ✅ Apache 2.0 | Source-avail. | ✅ MIT | ✅ MIT | ✅ AGPL-3.0 | ✅ MIT | ✅ MIT | ✅ MIT | CC BY-NC-SA | ✅ MIT | ✅ MIT |
| Self-hosted | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Kubernetes native | ✅ | ❌ | ❌ | ✅ | ✅ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Helm charts | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Docker Compose | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Protocol-driven DI | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Language | Python | TS/Rust | Python/TS | .NET/Python | Go | Python/TS | Python | TS | Python | Python | TS |

### Analysis

**Stronghold's position:** Full-stack self-hosted platform with both Docker Compose (dev) and Kubernetes + Helm (production). Protocol-driven DI means every external dependency (LiteLLM, PostgreSQL, Arize) is behind a swappable interface — 20 protocols, zero direct imports in business logic. Complete redesign from Maistro/Conductor learnings (March 25, 2026).

**Closest competitors:**
- **MS Agent Framework** is the only other framework with comparable deployment maturity (K8s, Helm) AND protocol-driven architecture. However, its full feature set is tightly coupled to Azure AI Foundry.
- **Archestra** ships K8s-native with Terraform + Helm but is AGPL-3.0 (copyleft), which limits commercial embedding. Go-based (vs Stronghold's Python).
- Most others (OpenAI Agents SDK, CrewAI, LangGraph, Deep Agents, Pi) are libraries you `pip install` — they provide orchestration primitives, not deployment infrastructure.

**Licensing note:** Stronghold (Apache 2.0) and most MIT-licensed frameworks allow unrestricted commercial use. Archestra's AGPL-3.0 requires derivative works to be open-sourced. Hyperagents' CC BY-NC-SA prohibits commercial use entirely.

---

## 2. Multi-Agent Orchestration

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-agent support | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 | ❌ |
| Shipped agent roster | ✅ 6 agents | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Reasoning strategies | ✅ 4 generic + custom | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| A2A communication | ✅ | ✅ | ✅ Handoffs | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| Intent classification | ✅ Keyword + LLM | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-intent parallel dispatch | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tournament evolution | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Dynamic intent creation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Proactive behavior (Reactor) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 Cron | ❌ | ❌ | ❌ |
| Agent import/export | ✅ GitAgent | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Analysis

**Stronghold's position:** Ships 6 production-ready specialist agents (Arbiter, Artificer, Scribe, Ranger, Warden-at-Arms, Forge) — no other framework does this. All orchestration features were in the initial commit, redesigned from Maistro/Conductor learnings; the Builders 2.0 pipeline (Frank + Mason) and learning strategy were added in the first week (April 1–2, 2026).

**Shipped agent roster** — Every other framework expects you to build your own agents from primitives. Stronghold ships opinionated specialists with defined roles, trust boundaries, and tool permissions. CrewAI's role/goal/backstory pattern is conceptually similar but requires you to define every agent yourself.

**Reasoning strategies** — Stronghold provides 4 generic strategies (direct, react, plan_execute, delegate) that any imported agent can use without writing Python, plus custom strategies for specialists. LangGraph achieves similar flexibility through graph node composition. CrewAI has sequential/hierarchical/consensual process types. MS Agent Framework supports sequential, concurrent, handoff, and group chat patterns.

**Tournament evolution** — Unique to Stronghold. 5–10% of requests run two agents on the same task. Scored by LLM-as-judge, tool success rate, and user feedback. Winners earn routes automatically. No other framework has automated agent competition.

**Dynamic intent creation** — Unique to Stronghold. When an agent is imported with capabilities that don't fit existing intents, the system creates a new intent category from the agent's declared keywords. No manual routing table updates.

**Proactive behavior** — Stronghold's Reactor is a 1000Hz event loop that unifies event-driven, interval, time, and state triggers. OpenClaw has basic cron scheduling. No other framework has a general-purpose proactive agent runtime.

**GitAgent import/export** — Unique to Stronghold. Clone a git repo, run `stronghold agent import`, and the agent's YAML, prompts, memories, tools, and strategy are loaded into the running system. Export round-trips cleanly. No other framework has a portable agent format.

---

## 3. Security & Governance

This is Stronghold's primary differentiator. Security is not a feature — it is the architectural foundation. Every design decision starts with "how can this be exploited?" The entire security stack (Warden, Gate, Sentinel, trust tiers) was designed from first principles for the initial commit (March 25, 2026), informed by Maistro/Conductor learnings but rebuilt with security as the unitary design principle rather than one concern among many.

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Input scanning | ✅ Warden | ❌ | ✅ Input guardrails | ✅ Content Safety | ✅ Dual-LLM | 🟡 NeMo | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Tool result scanning | ✅ Warden | ❌ | ✅ Tool guardrails | ✅ Middleware | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Output scanning | ✅ Sentinel | ✅ Sandboxed | ✅ Output guardrails | ✅ Content Safety | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Trust tiers | ✅ 5-tier | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Schema validation & repair | ✅ Sentinel | ❌ | ✅ Pydantic | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| PII filtering | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Config-driven RBAC | ✅ | 🟡 | ❌ | ✅ Entra ID | ✅ | 🟡 Platform | 🟡 AMP | ❌ | ❌ | ❌ | ❌ |
| Per-agent tool permissions | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Audit logging | ✅ | ❌ | ✅ Traces | ✅ | ✅ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Rate limiting | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Sandbox execution | ✅ Containers | ✅ bubblewrap | ✅ | ✅ | ✅ K8s | ❌ | ❌ | 🟡 Docker | ✅ Docker | ❌ | ❌ |
| Zero-trust architecture | ✅ | ❌ | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Analysis

**Stronghold's position:** The only framework where security is the foundational design principle, not an add-on. Three dedicated security components — Warden (threat detection), Sentinel (policy enforcement), Gate (input processing) — cover every trust boundary in the system. All shipped in the initial commit.

**Three-boundary scanning** — Only 4 frameworks scan at all three boundaries (input, tool results, output): Stronghold, OpenAI Agents SDK, MS Agent Framework, and Archestra. The approaches differ significantly:
- **Stronghold:** Warden uses cheap-to-expensive layering (regex → heuristics → LLM) that short-circuits on detection. Sentinel handles policy enforcement as a LiteLLM guardrail plugin. Both scan tool results — indirect prompt injection through tool output is one of the most underestimated attack vectors.
- **OpenAI Agents SDK:** Input/output/tool guardrails run in parallel with agent execution, fail-fast. Clean design but guardrails must be explicitly wired per agent.
- **MS Agent Framework:** Azure AI Content Safety integration with agent middleware pipeline. Strongest when deployed on Azure; less capable standalone.
- **Archestra:** Dual-LLM architecture isolates dangerous tool responses in a security sub-agent. Novel approach to prompt injection prevention.

**Trust tiers** — Only Stronghold and MS Agent Framework have tiered trust. Stronghold's 5-tier system (☠️ Skull → T3 Forged → T2 Community → T1 Installed → T0 Built-in) with earned promotion through automated validation is more granular. Output from the Forge agent starts at ☠️ and must pass security scanning to promote. No tool or agent auto-promotes past T3 without operator approval or tournament evidence.

**Schema validation & repair** — Stronghold's Sentinel doesn't just validate tool-call arguments against MCP schemas — it repairs them. Fuzzy-matches hallucinated field names to real ones, coerces types, applies defaults. Repairs feed back into the learning system. OpenAI Agents SDK validates via Pydantic but doesn't repair.

**Zero-trust** — Stronghold scans all three trust boundaries (user input, tool results, agent output) with dedicated components at each. MS Agent Framework and Archestra have partial zero-trust postures (strong at the boundary, weaker internally). The March 2026 "Governance Architecture for Autonomous Agent Systems" paper (arXiv:2603.07191) describes a comparable 4-layer security framework — Maistro's input scanning (February 19) predates it, but the convergence validates the multi-layer approach.

**OpenClaw security note:** OpenClaw accumulated 138 CVEs in its first 5 months (7 critical, 49 high). A systematic taxonomy paper (arXiv 2603.27517) catalogs 190 security advisories. Nvidia released NemoClaw as a third-party security add-on. Enterprise use without additional hardening is not recommended.

---

## 4. Memory & Learning

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Session memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Episodic memory (7-tier) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Self-improving learnings | ✅ | 🟡 Auto-memory | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Memory scopes (5 levels) | ✅ | ❌ | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Knowledge/RAG (pgvector) | ✅ | ❌ | 🟡 | ✅ | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Memory decay & reinforcement | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Auto-promotion of corrections | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| RASO (self-modifying agent graph) | 🗺️ Native | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Research | ❌ | ❌ |

### Analysis

**Stronghold's position:** Memory is where Stronghold is most differentiated. No other platform combines learning extraction, tiered episodic memory with decay, 5-level scoping, and auto-promotion of corrections. The learning store was redesigned from Maistro patterns; the builders learning strategy (repo recon + self-diagnosis) was added April 2, 2026.

**7-tier episodic memory** — Unique to Stronghold. Originated in **CoinSwarm**, a biological-evolution-inspired hybrid micro-agent + statistical engine swarm that evolves as a collective population through economically powered selection pressure for cryptocurrency and equities trading (achieving minimal alpha while drastically minimizing downside risk). The tiered memory model — where memories have structural weight bounds, regrets (≥0.6) are structurally unforgettable, and wisdom (≥0.9) is near-permanent — was designed so the swarm could never forget catastrophic losses or hard-won risk insights. Stronghold adopted and generalized this for agent governance: the system structurally cannot forget its worst mistakes or most important lessons. No other framework has tiered memory with enforced weight floors.

**Self-improving learnings** — Stronghold extracts fail→succeed patterns from tool-call history automatically. When a tool call fails with args A and succeeds with args B, the system stores the correction with trigger keywords. After N successful injections, the correction auto-promotes to a permanent prompt addition and optionally bridges to episodic memory (LESSON tier). Closest comparisons:
- **Claude Code** has auto-memory that saves build commands and debugging insights across sessions, but these are static notes, not extracted from failure patterns.
- **Hyperagents** has the most advanced self-improvement (metacognitive self-modification where the improvement mechanism itself is editable), but it's research code under CC BY-NC-SA — non-commercial, not importable as a library.

**5 memory scopes** — global (all agents, all users) → team (same domain) → user (all agents, one user) → agent (one agent) → session (one conversation). Retrieval is a single query ranked by `similarity(content, query) * weight` with scope filtering. MS Agent Framework has pluggable memory backends (Mem0, Redis, Neo4j) but no structured scope hierarchy. CrewAI has custom memory interfaces but less documented.

**Memory decay & reinforcement** — Unique to Stronghold. Memories decay without reinforcement (observations fade, hypotheses weaken). Reinforced memories gain weight. This prevents unbounded memory growth while preserving structurally important knowledge. No other framework implements automatic decay.

**RASO (Reflexive Agentic Self-Optimization)** — Roadmapped. The core concept — agents improving via structured feedback from other agents — traces back to CoinSwarm's evolutionary fitness loops (January 2026, 9 weeks before Meta's [Hyperagents](https://arxiv.org/abs/2603.19461) paper) and Maistro's trace reviewer (February 2026, 4 weeks before). Stronghold's feedback module (April 2, 2026) was developed without knowledge of HyperAgents (discovered April 16). The RASO meta-layer — wrapping a meta-agent around the builders graph so it can modify its own structure — was influenced by HyperAgents after discovery. Previously called "naive RLHF" internally; renamed because the feedback is primarily agent-driven (tournaments, learning extraction, quality gates), with optional human feedback via PR comments.

---

## 5. Model Routing

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-model support | ✅ | 🟡 Anthropic | 🟡 OpenAI | ✅ Foundry | ✅ | ✅ Portkey | ✅ LiteLLM | ✅ | 🟡 | 🟡 | ✅ |
| Intelligent cost/quality routing | ✅ Scarcity-based | ❌ | ❌ | ❌ | ✅ Dynamic optimizer | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Automatic fallback (429/5xx) | ✅ | ❌ | ❌ | ✅ | ✅ | 🟡 | 🟡 | ✅ | ❌ | ❌ | ✅ |
| Task-type speed bonuses | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Token budget enforcement | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### Analysis

**Stronghold's position:** Scarcity-based model routing was originally developed in the Conductor routing layer and first git-committed in Stronghold's initial commit (March 25, 2026). The scoring formula `score = quality^(qw*p) / (1/ln(remaining_tokens))^cw` makes cost rise smoothly as provider token pools deplete — no cliffs, no manual rebalancing. The router module (scorer, scarcity, speed, filter, selector) totals ~400 lines.

**Intelligent routing** — Only Stronghold and Archestra have cost/quality-aware routing:
- **Stronghold:** Scarcity-based scoring. Filters by tier/quota/status, scores by quality/speed/strength, selects best model. Task-type bonuses shift weights (voice gets speed, code gets quality).
- **Archestra:** Dynamic optimizer claims up to 96% cost reduction by automatically switching to cheaper models when quality thresholds are met. Different approach — Archestra optimizes for cost floor, Stronghold optimizes for quality ceiling within budget.

**Task-type speed bonuses** — Unique to Stronghold. The router weights quality, speed, and strength differently based on the classified task type. A voice request prioritizes latency. A code request prioritizes reasoning quality. A search request prioritizes throughput. No other framework adjusts model selection based on task classification.

**Multi-model support** — Most frameworks are model-agnostic through middleware (LiteLLM, Portkey, direct SDK calls). Claude Code and OpenAI Agents SDK are optimized for their own models but support alternatives. Stronghold routes through LiteLLM, giving access to any provider LiteLLM supports.

**Fallback** — Stronghold, MS Agent Framework, Archestra, OpenClaw, and Pi all handle provider failures with automatic fallback to alternative models. LangGraph and CrewAI have partial support through their LLM middleware layers.

---

## 6. Tool Ecosystem

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| MCP support | ✅ via LiteLLM | ✅ | ✅ | ✅ | ✅ Registry | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| AI tool/agent creation (Forge) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| OpenAPI auto-conversion | ✅ via LiteLLM | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Skill marketplace | ✅ | ❌ | ❌ | ✅ Foundry | ✅ 858+ servers | ❌ | ❌ | ✅ ClawHub | ❌ | ❌ | ❌ |

### Analysis

**Stronghold's position:** MCP support via LiteLLM gateway (not a custom implementation), OpenAPI auto-conversion, skill marketplace, and the Forge agent for AI-driven tool creation. All in the initial commit, redesigned from Maistro/Conductor learnings.

**Forge (AI tool/agent creation)** — Unique to Stronghold. The Forge agent creates tools and agents autonomously, validates them through security scanning, and starts output at ☠️ trust tier. The creation flow (LLM generates SKILL.md → security scan → schema validation → save) ensures created artifacts pass security review before promotion to T3. No other framework has an agent that creates other agents and tools with automated security validation.

**MCP support** — 5 frameworks support MCP natively: Stronghold (via LiteLLM), Claude Code, OpenAI Agents SDK, MS Agent Framework, and Archestra. Archestra has the largest registry (858+ MCP servers). Stronghold delegates MCP protocol handling entirely to LiteLLM rather than implementing its own gateway — this means Stronghold gets MCP improvements for free as LiteLLM evolves.

**OpenAPI auto-conversion** — Stronghold and MS Agent Framework both auto-convert OpenAPI specs to callable tools. Stronghold does this through LiteLLM's OpenAPI-to-MCP conversion. Point at any OpenAPI spec, get MCP-compatible tools.

---

## 7. Observability

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OTEL tracing | ✅ Phoenix | ✅ | ✅ | ✅ | ✅ Prometheus | ✅ LangSmith | ✅ | ❌ | ❌ | 🟡 | ❌ |
| Prompt management | ✅ PostgreSQL | ❌ | ❌ | ❌ | ❌ | 🟡 LangSmith | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cost tracking | ✅ LiteLLM | ❌ | ❌ | ✅ | ✅ | 🟡 Portkey | ❌ | ❌ | ❌ | ❌ | ✅ |

### Analysis

**Stronghold's position:** Full observability stack — OTEL tracing to Arize Phoenix, self-hosted prompt management in PostgreSQL, and per-request cost tracking through LiteLLM callbacks. All observability components are behind protocol interfaces (`TracingBackend`, `PromptManager`) so backends are swappable.

**Prompt management** — Stronghold stores prompts in PostgreSQL with versioning, labels (production/staging), and structured metadata. Hot-reload via LISTEN/NOTIFY. No external SaaS dependency. LangGraph uses LangSmith for prompt management but that's a commercial SaaS product. No other framework has self-hosted prompt management built in.

**Tracing** — Every request is a trace, every boundary crossing is a span. The trace tree covers: warden scan → gate → classify → route → agent.handle → prompt build → LLM calls → tool calls → learning extraction → response. Most frameworks with OTEL support provide less granular span trees.

---

## 8. Enterprise & Multi-Tenant

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-tenant isolation | 🗺️ | ❌ | ❌ | ✅ | ✅ | ✅ Platform | 🟡 AMP | ❌ | ❌ | ❌ | ❌ |
| SSO / OIDC | ✅ Keycloak + Entra | ✅ Enterprise | ❌ | ✅ Entra ID | ❌ | ✅ Platform | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Namespace-scoped secrets | 🗺️ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Agent marketplace | 🗺️ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Analysis

**Stronghold's position:** SSO/OIDC is implemented (Keycloak + Entra ID, shipped in initial commit). Multi-tenant isolation, namespace-scoped secrets, and agent marketplace are roadmapped. This is Stronghold's weakest category today — MS Agent Framework, Archestra, and LangGraph Platform all have production multi-tenancy.

**SSO** — Stronghold supports both Keycloak (open-source default) and Entra ID (enterprise Microsoft shops) through the `AuthProvider` protocol. Static API keys for service-to-service. OpenWebUI header passthrough for thin-client deployments.

**Multi-tenant isolation (roadmapped)** — Designed as per-tenant K8s namespaces, each with scoped LiteLLM API keys, scoped Arize projects, and memory filtered by tenant_id. MS Agent Framework has this today through Azure AI Foundry. Archestra has per-org/team/agent scoping. LangGraph Platform (commercial) has multi-tenancy with SOC 2 Type 2 compliance.

**Where Stronghold trails:** MS Agent Framework and Archestra both have agent/tool registries (marketplaces) and per-tenant secret management in production today. These are Stronghold's most significant gaps for enterprise adoption.

---

## 9. CI & Quality Gates

How each project enforces code quality, security, and test rigor at merge time. Most agent frameworks don't publish their CI configs, so some cells are `❓` (no public evidence) rather than `❌`.

### 9.1 Security Gates

Requirements:

- **SAST** — Bandit (Python-specific patterns), Semgrep (multi-language security rules)
- **Supply chain** — pip-audit / dependabot (CVE scanning), optionally OSV-Scanner
- **Secret detection** — Gitleaks + custom regex patterns over git history
- **Container** — Hadolint (Dockerfile lint), optionally Trivy for image CVEs
- **Code flow** — CodeQL (GHAS) for multi-language security queries

| Tool | Stronghold | Claude Code | OpenAI SDK | MS Agent | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Bandit | ✅ blocking | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ |
| Semgrep | ✅ blocking | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ |
| pip-audit / dependabot | ✅ warn | 🟡 dependabot | 🟡 dependabot | 🟡 dependabot | 🟡 dependabot | 🟡 dependabot | 🟡 dependabot | ❓ | ❓ | ❓ |
| Gitleaks | ✅ blocking | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ |
| Hadolint | ✅ blocking | N/A | N/A | ❓ | N/A | N/A | N/A | N/A | N/A | N/A |
| CodeQL | ✅ blocking | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ | ❓ |

**Industry baseline (OWASP ASVS L2, SLSA L2):** SAST required, supply-chain scanning required, secrets detection required, container hardening recommended. Most published CI configs for enterprise OSS ship 2-3 of these; Stronghold ships all 5 as blocking plus CodeQL.

### 9.2 Code Quality Gates

Requirements:

- **Style/lint** — Ruff (replaces flake8 + isort + pylint + pyupgrade, ~100× faster)
- **Types** — Mypy `--strict` (enforces `Any` escape hatches, unreachable code, untyped defs)
- **Complexity** — Xenon (wraps radon for CI — `--max-absolute` ranked A-F)
- **Dead code** — Vulture (conservative `--min-confidence 100` + whitelist)

| Tool | Stronghold | Typical OSS lib | Typical SaaS | Regulated (finance/health) |
|---|:---:|:---:|:---:|:---:|
| Ruff (lint + format) | ✅ blocking, full codebase | ✅ common | ✅ | ✅ |
| Mypy `--strict` | ✅ blocking on changed files | 🟡 often `--strict-optional` only | 🟡 | ✅ |
| Xenon (complexity) | ✅ blocking | ❌ rare | 🟡 occasional | 🟡 |
| Vulture (dead code) | ✅ blocking with whitelist | ❌ rare | ❌ | 🟡 |

**Industry baseline:** Ruff + Mypy is standard. Complexity and dead-code gates are uncommon — most projects rely on human code review to catch those. Stronghold runs both to reduce reviewer load and catch creeping complexity early.

### 9.3 Coverage Gates

Requirements:

- **Unit coverage** — per-branch thresholds (stricter closer to release)
- **Integration coverage** — full-pipeline tests with real DB, real protocols
- **Diff coverage** — measured only on lines changed in the PR

| Gate | Stronghold | Typical OSS | Typical SaaS | Regulated |
|---|:---:|:---:|:---:|:---:|
| Feature-branch → feature-parent | 85% | 70-80% | 80% | 85-90% |
| Feature → integration | 90% | — (flat) | 80-85% | 90% |
| Integration → main (diff coverage) | 95% | — | 85-90% | 95% |

**Industry baseline:** Coverage thresholds vary. Academic study ([Hilton et al., MSR 2016](https://cmhilton.com/papers/hilton-msr-2016-coverage.pdf)) found median CI coverage requirement for active OSS projects is ~75%. Regulated sectors (FAA DO-178C, IEC 62304) mandate branch coverage in the 85-100% range depending on criticality level. Stronghold's tiered 85/90/95 matches the regulated-sector bar without being flat.

### 9.4 Test Assertion Strength

Requirements (none of which existed as industry-standard gates before):

- **Pattern linter** — AST-level detection of weak patterns: `status_code in (…)` tolerance, `isinstance` right after construction, `hasattr` tautologies, no-assert test bodies, over-mocking of internal protocols
- **LLM assertion judge** — Classify each new/changed test as GOOD / WEAK / BAD against a rubric, seeded with a golden-set of verified examples
- **Mutation testing** — Targeted `mutmut` run on src files whose tests changed; flag tests that don't kill plausible mutations

| Gate | Stronghold | Industry |
|---|:---:|:---:|
| Pattern linter | 🗺️ stage 1 | ❌ |
| LLM assertion judge | 🗺️ stage 2 | ❌ |
| Mutation testing | 🗺️ stage 3 | 🟡 academic research, rare in production SaaS |

**Why this matters:** the Apr 17 test-quality audit cataloged 3,775 tests and found ~9% with assertions too weak to catch the regressions they claimed to guard against. The issue wasn't coverage — 94% raw coverage hid a long tail of weak assertions. Assertion-strength gates close that gap.

**Industry baseline on mutation testing:** academic studies ([Petrovic et al., Google, 2018](https://research.google/pubs/state-of-mutation-testing-at-google/)) report mutation scores of 60-85% for well-tested Python codebases. Google ships mutation testing as a human-surfaced hint (not a hard gate); Stronghold's design proposes the same — mutation score flags WEAK tests but doesn't auto-block, giving humans the review context.

### Analysis

**Stronghold's position:** full security-gate stack (Bandit + Semgrep + pip-audit + Gitleaks + Hadolint + CodeQL) + broad code-quality gates (Ruff + Mypy-strict + Xenon + Vulture) + tiered coverage (85/90/95) + roadmapped assertion-strength gate. This is the densest CI stack in the comparison and is currently unique in the agent-framework space.

**Where the comparison is honest:** most of the security-tool competitor columns are `❓` because competitors don't publish CI configs. Claims would be unverifiable. Coverage comparisons use published industry baselines rather than per-competitor claims.

**Where the gap is real:** the assertion-strength gate is unique. No framework gates on whether a test's assertion actually catches a regression. Design lives at `docs/test-quality-audit-and-ci-gate-proposal.md`; implementation is phased (AST linter → LLM judge → mutation testing).
