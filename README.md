<div align="center">

<br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/%F0%9F%8F%B0-STRONGHOLD-white?style=for-the-badge&labelColor=1a1a2e&color=16213e">
  <img alt="Stronghold" src="https://img.shields.io/badge/%F0%9F%8F%B0-STRONGHOLD-black?style=for-the-badge&labelColor=f5f5f5&color=e8e8e8">
</picture>

<br><br>

### Secure Agent Governance Platform

<br>

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-ready-326ce5.svg?style=flat-square&logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Tests](https://img.shields.io/badge/Tests-2%2C785_passing-brightgreen.svg?style=flat-square&logo=pytest&logoColor=white)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-95%25-brightgreen.svg?style=flat-square)](pyproject.toml)
[![mypy](https://img.shields.io/badge/mypy-strict-blue.svg?style=flat-square)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square)](https://github.com/astral-sh/ruff)

<br>

**Wrap any LLM in a secure execution harness with intelligent routing,**
**self-improving memory, autonomous operation, and zero-trust security.**

<sub>Running in production. Now targeting k8s-native v0.9 with near-full feature set.</sub>

<br>

[Architecture](ARCHITECTURE.md) &nbsp;&bull;&nbsp; [Security](SECURITY.md) &nbsp;&bull;&nbsp; [Roadmap](ROADMAP.md) &nbsp;&bull;&nbsp; [Onboarding](ONBOARDING.md) &nbsp;&bull;&nbsp; [ADRs](docs/adr/)

<br>

</div>

---

<br>

> [!IMPORTANT]
> **All input is untrusted. All tool output is untrusted. Trust is earned, not assumed.**

<br>

## ✨ What Makes It Different

<table>
<tr>
<td width="50%">

### 📉 Scarcity-Based Routing
Cost rises smoothly as provider tokens are consumed. No cliffs, no manual rebalancing.

### 🧠 Self-Improving Memory
Learns from tool-call failures. Auto-promotes corrections after N successful injections.

### 💎 7-Tier Episodic Memory
Regrets are structurally unforgettable. Wisdom survives across versions.

### 🛡️ Defense-in-Depth
4-layer Warden + Sentinel at every trust boundary. Cheap-to-expensive, short-circuit on detection.

</td>
<td width="50%">

### ⚒️ Skill Forge
AI creates its own tools. Validates via security scanner. Output starts at ☠️ trust tier.

### ⚡ Multi-Intent Parallel Dispatch
Compound requests split into scoped subtasks. Dispatched to specialist agents in parallel.

### 🎯 Task-Type-Aware Routing
Voice gets speed weight. Code gets quality weight. Every task type has tuned scoring.

### 🏆 Tournament Evolution
Agents compete head-to-head. Winners earn routes. Losers get demoted.

</td>
</tr>
</table>

<br>

---

<br>

## 📊 Project Status

<div align="center">

**Phases 1--4 complete** &nbsp;&bull;&nbsp; **3 security audits** &nbsp;&bull;&nbsp; **1 live red team** &nbsp;&bull;&nbsp; **Building toward k8s-native v0.9**

</div>

<br>

<table>
<tr>
<td align="center"><strong>2,785</strong><br><sub>Tests Passing</sub></td>
<td align="center"><strong>155+</strong><br><sub>Source Files</sub></td>
<td align="center"><strong>11,500</strong><br><sub>Lines of Code</sub></td>
<td align="center"><strong>0</strong><br><sub>mypy Errors</sub></td>
<td align="center"><strong>95%</strong><br><sub>Coverage Target</sub></td>
<td align="center"><strong>213</strong><br><sub>Adversarial Samples</sub></td>
</tr>
</table>

<br>

<details>
<summary>&nbsp;✅&nbsp;&nbsp;<b>What's Built (Phases 1--4)</b></summary>

<br>

**Phase 1: Security Backbone** -- Gate (sanitize + Warden + sufficiency), Warden (4-layer: regex, heuristic, semantic tool-poisoning, LLM classifier), Sentinel (schema validation + repair + PII filter), JWT auth (IdP-agnostic), audit logging, SSRF blocklist

**Phase 2: Memory Backbone** -- Pluggable embeddings (Ollama/OpenAI), hybrid learning store (keyword + cosine), episodic retrieval (org-scoped, weight-ranked), session store with ownership validation, outcome store

**Phase 3: Skill System** -- Parser (YAML + markdown), loader (filesystem + community), registry (CRUD + trust tiers), Forge (LLM skill creation, security scan, mutation from learnings), marketplace (HTTP install, SSRF protection)

**Phase 4: Tool Framework + UI** -- Tool registry, tool dispatcher (timeout, SSRF), 6 API route groups, 6 castle-themed dashboard pages (Great Hall, Knights, Armory, Watchtower, Treasury, Scrolls), all XSS-free

**Security Hardening** -- 30+ vulnerabilities fixed across 2 enterprise audits + 42 findings in round 3. OWASP mapped: Web 2021, LLM 2025, API 2023.

</details>

<br>

---

<br>

## 🏗️ Architecture

### Request Flow

```mermaid
flowchart TD
    A["POST /v1/chat/completions"] --> B["🔐 Auth"]
    B --> C["🚪 Gate"]
    C --> D["🛡️ Warden Scan"]
    D --> E["🎯 Classifier"]
    E --> F{"Ambiguous?"}
    F -->|Yes| G["⚖️ Arbiter"]
    F -->|No| H["📋 Intent Registry"]
    G --> H
    H --> I["🤖 Agent.handle()"]
    I --> J["🛡️ Warden Scan"]
    J --> K["🧩 Context Builder"]
    K --> L["🎲 Strategy.reason()"]
    L --> M["🧠 Extract Learnings"]
    M --> N["🛡️ Warden Scan"]
    N --> O["📤 Response"]

    style A fill:#4a90d9,color:#fff
    style D fill:#e74c3c,color:#fff
    style J fill:#e74c3c,color:#fff
    style N fill:#e74c3c,color:#fff
    style I fill:#2ecc71,color:#fff
    style O fill:#4a90d9,color:#fff
```

### Deployment Stack

```mermaid
graph LR
    OW["🌐 OpenWebUI<br>:3000"] --> PP["🔗 Pipelines<br>:9099"]
    PP --> SH["🏰 Stronghold API<br>:8100"]
    SH --> LL["🔀 LiteLLM<br>:4000"]
    LL --> LLM["☁️ LLM Providers"]
    LL --> MCP["🔧 MCP Servers"]
    SH --> PG["🐘 PostgreSQL<br>+ pgvector"]
    SH --> PX["📊 Arize Phoenix<br>:6006"]

    style SH fill:#2ecc71,color:#fff,stroke-width:3px
    style PG fill:#336791,color:#fff
    style LL fill:#ff6b35,color:#fff
```

<br>

### 🤖 Agent Roster

<table>
<tr>
<td align="center" width="16%">
<br>
<strong>⚖️</strong><br>
<strong>Arbiter</strong><br>
<sub>delegate</sub><br><br>
<sub>Triages ambiguous requests. Clarifies, then delegates to specialists.</sub>
<br><br>
</td>
<td align="center" width="16%">
<br>
<strong>🔨</strong><br>
<strong>Artificer</strong><br>
<sub>plan_execute</sub><br><br>
<sub>Code agent. Sub-agents: planner, coder, reviewer, debugger.</sub>
<br><br>
</td>
<td align="center" width="16%">
<br>
<strong>✍️</strong><br>
<strong>Scribe</strong><br>
<sub>plan_execute</sub><br><br>
<sub>Writing specialist. Committee: researcher, drafter, critic, editor.</sub>
<br><br>
</td>
<td align="center" width="16%">
<br>
<strong>🔍</strong><br>
<strong>Ranger</strong><br>
<sub>react</sub><br><br>
<sub>Read-only search. Output always Warden-scanned.</sub>
<br><br>
</td>
<td align="center" width="16%">
<br>
<strong>⚔️</strong><br>
<strong>Warden-at-Arms</strong><br>
<sub>react</sub><br><br>
<sub>Device control, API calls, runbook execution.</sub>
<br><br>
</td>
<td align="center" width="16%">
<br>
<strong>🔥</strong><br>
<strong>Forge</strong><br>
<sub>react</sub><br><br>
<sub>Creates tools & agents. Output starts at ☠️ tier.</sub>
<br><br>
</td>
</tr>
</table>

<br>

### 🔐 Trust Tiers

<table>
<tr>
<td align="center">☠️<br><strong>Skull</strong><br><sub>In the Forge.<br>Cannot be used.</sub></td>
<td align="center">→</td>
<td align="center">🟡<br><strong>T3 Forged</strong><br><sub>Passed Forge QA.<br>Sandboxed. Read-only.</sub></td>
<td align="center">→</td>
<td align="center">🟠<br><strong>T2 Community</strong><br><sub>Marketplace install<br>or operator-approved.</sub></td>
<td align="center">→</td>
<td align="center">🟢<br><strong>T1 Installed</strong><br><sub>Operator-vetted.<br>Full tool access.</sub></td>
<td align="center">→</td>
<td align="center">💚<br><strong>T0 Built-in</strong><br><sub>Shipped with Stronghold.<br>Core trust.</sub></td>
</tr>
</table>

> [!NOTE]
> Promotion path: ☠️ → T3 (Forge QA passes) → T2 (N successful uses, no Warden flags) → T1 (operator approval). **Never auto-promotes to T0.**

<br>

### 🧩 Protocol-Driven DI

All business logic depends on protocols, never concrete implementations. The DI container wires everything:

<div align="center">

`LLMClient` · `LearningStore` · `AuthProvider` · `IntentClassifier` · `ModelRouter`

`QuotaTracker` · `PromptManager` · `TracingBackend` · `ToolRegistry` · `SkillRegistry`

<sub>Every external dependency (LiteLLM, Arize, PostgreSQL, auth providers) is swappable without touching business logic.</sub>

</div>

<br>

---

<br>

## 🚀 Quick Start

### Docker Compose (Development)

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up -d
```

<table>
<tr>
<th>Service</th>
<th>Port</th>
<th>Purpose</th>
</tr>
<tr><td>🏰 Stronghold API</td><td><code>8100</code></td><td>Agent governance platform</td></tr>
<tr><td>🐘 PostgreSQL + pgvector</td><td><code>5432</code></td><td>Memory, sessions, audit, prompts</td></tr>
<tr><td>📊 Arize Phoenix</td><td><code>6006</code></td><td>Trace storage and dashboards</td></tr>
<tr><td>🔀 LiteLLM</td><td><code>4000</code></td><td>Model proxy + MCP gateway</td></tr>
<tr><td>🔗 Pipelines</td><td><code>9099</code></td><td>OpenWebUI governance bridge</td></tr>
<tr><td>🌐 OpenWebUI</td><td><code>3000</code></td><td>Chat interface</td></tr>
</table>

```bash
# Health check
curl http://localhost:8100/health

# Send a request
curl -X POST http://localhost:8100/v1/chat/completions \
  -H "Authorization: Bearer $ROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

### ☸️ Kubernetes (Production)

Stronghold targets Kubernetes for production deployment with multi-tenant namespace isolation, deploying to k3s (with OKD/OCP as Tier-1 reference runtimes). See [ADRs](#-architecture-decision-records) for the full deployment design.

<br>

---

<br>

## 🛠️ Development

<table>
<tr>
<td>

**Python 3.12+** -- install dev dependencies:

```bash
pip install -e ".[dev]"
```

</td>
</tr>
</table>

<br>

<table>
<tr>
<td width="50%">

#### 🧪 Run Tests

```bash
# All tests
pytest tests/ -v

# Single file
pytest tests/routing/test_selector.py -v

# Single test
pytest tests/ -v -k "test_claim_returns_none"
```

</td>
<td width="50%">

#### ✅ All Checks (CI Equivalent)

```bash
pytest tests/ -v && \
ruff check src/stronghold/ && \
ruff format --check src/stronghold/ && \
mypy src/stronghold/ --strict && \
bandit -r src/stronghold/ -ll
```

</td>
</tr>
</table>

```bash
# Pre-commit hooks
pre-commit install && pre-commit run --all-files
```

<details>
<summary>&nbsp;⚙️&nbsp;&nbsp;<b>Environment Variables</b></summary>

<br>

YAML config loaded from `STRONGHOLD_CONFIG` env var (default: `config/example.yaml`).

| Variable | Purpose | Default |
|----------|---------|---------|
| `ROUTER_API_KEY` | API authentication key | `sk-example-stronghold` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://stronghold:stronghold@localhost:5432/stronghold` |
| `LITELLM_URL` | LiteLLM proxy URL | `http://litellm:4000` |
| `LITELLM_MASTER_KEY` | LiteLLM admin key | `sk-example-litellm` |
| `PHOENIX_COLLECTOR_ENDPOINT` | Arize Phoenix URL | `http://phoenix:6006` |
| `KUBECONFIG` | Kubernetes cluster config | -- |
| `KEYCLOAK_ISSUER` | Keycloak OIDC issuer URL | -- |
| `ENTRA_TENANT_ID` | Azure Entra ID tenant | -- |
| `ENTRA_CLIENT_ID` | Azure Entra ID client | -- |

</details>

<br>

<details>
<summary>&nbsp;📁&nbsp;&nbsp;<b>Project Structure</b></summary>

<br>

```
src/stronghold/
├── protocols/          # 🧩 Abstract interfaces (the skeleton)
├── types/              # 📦 Shared value objects + error hierarchy
├── classifier/         # 🎯 Intent classification (keyword + LLM fallback + multi-intent)
├── router/             # 📉 Model selection (scarcity-based scoring)
├── security/
│   ├── warden/         # 🛡️ 4-layer threat detection (regex + heuristic + semantic + LLM)
│   └── sentinel/       # 🔒 LiteLLM guardrail (schema repair, token opt, audit)
├── memory/
│   ├── learnings/      # 🧠 Self-improving corrections
│   └── episodic/       # 💎 7-tier weighted memories
├── agents/
│   ├─�� strategies/     # 🎲 Generic: direct, react, plan_execute, delegate
│   ├── artificer/      # 🔨 Code agent (plan + code + test + review)
│   ├── scribe/         # ✍️ Writing agent (committee pattern)
│   ├── forge/          # 🔥 Tool/agent creator
│   └── warden_at_arms/ # ⚔️ Device/API control
├── skills/             # ⚡ Skill ecosystem (parse, load, forge, marketplace)
├── tools/              # 🔧 MCP tool registry + legacy wrappers
├── tracing/            # 📊 Arize Phoenix / Enterprise backend
├── api/                # 🌐 FastAPI transport layer
├── config/             # ⚙️ YAML config loader + env resolution
├── builders/           # 🏗️ Automated build orchestration (Mason/Artificer)
├── cache/              # 💾 Redis pool, rate limiter, session + prompt caches
├── quota/              # 🪙 Token tracking + coin economy
├── sessions/           # 💬 Conversation history
├── prompts/            # 📝 PostgreSQL-native prompt management
├── mcp/                # 🔌 MCP server integration
├── persistence/        # 🗄️ Data access layer
├── scheduling/         # ⏰ Reactor (1000Hz event loop) + proactive triggers
├── container.py        # 🏭 DI container (wires protocols to implementations)
└── conduit.py          # 🔀 Request pipeline (classify → route → dispatch)
```

</details>

<br>

---

<br>

## 📦 Agent Import/Export

<div align="center">

*Stronghold agents are portable. Import from any Git repository, export with accumulated learnings.*

</div>

<br>

<table>
<tr>
<td width="50%">

#### Import

```bash
stronghold agent import ./my-agent/
```

</td>
<td width="50%">

#### Export

```bash
stronghold agent export artificer ./export/
```
<sub>Includes updated prompts, accumulated memories, and learned corrections.</sub>

</td>
</tr>
</table>

<details>
<summary>&nbsp;📄&nbsp;&nbsp;<b>GitAgent Definition Format</b></summary>

<br>

```
my-agent/
├── agent.yaml          # ✅ Required — manifest (strategy, tools, permissions)
├── SOUL.md             # ✅ Required — system prompt / personality
├── RULES.md            # Hard constraints (must-always / must-never)
├── skills/             # SKILL.md files
├── tools/              # MCP-compatible tool definitions
├── memory/             # Seed memories (imported to pgvector)
├── knowledge/          # Reference docs (chunked + embedded for RAG)
├── strategy.py         # Custom deterministic logic (optional)
├── Dockerfile          # For untrusted custom strategies (containerized)
└── agents/             # Sub-agent definitions (recursive)
```

Example `agent.yaml`:

```yaml
spec_version: "0.1.0"
name: artificer
version: 1.0.0
description: Code and engineering specialist

soul: SOUL.md

reasoning:
  strategy: plan_execute
  max_rounds: 10
  review_after_each: true

model: auto
model_fallbacks: [mistral-large, gemini-2.5-pro]

tools: [file_ops, shell, test_runner, lint_runner, git]

memory:
  learnings: true
  episodic: true
  knowledge: true
  session: true
  scope: agent

trust_tier: t1

sub_agents:
  - artificer-planner
  - artificer-coder
  - artificer-reviewer
  - artificer-debugger
```

</details>

<br>

---

<br>

## 🧠 Memory System

<table>
<tr>
<td align="center" width="20%">🌍<br><strong>Global</strong><br><sub>All agents,<br>all users</sub></td>
<td align="center" width="20%">👥<br><strong>Team</strong><br><sub>Same<br>domain</sub></td>
<td align="center" width="20%">👤<br><strong>User</strong><br><sub>All agents,<br>one user</sub></td>
<td align="center" width="20%">🤖<br><strong>Agent</strong><br><sub>Only this<br>agent</sub></td>
<td align="center" width="20%">💬<br><strong>Session</strong><br><sub>Only this<br>conversation</sub></td>
</tr>
</table>

<br>

<details>
<summary>&nbsp;💎&nbsp;&nbsp;<b>Seven Episodic Tiers</b></summary>

<br>

| Tier | Weight | Behavior |
|------|--------|----------|
| 👁️ Observation | 0.1 -- 0.5 | Can decay to zero |
| 🔬 Hypothesis | 0.2 -- 0.6 | Can decay to zero |
| 💭 Opinion | 0.3 -- 0.8 | Slow decay |
| 📖 Lesson | 0.5 -- 0.9 | Resistant to decay |
| 😔 Regret | 0.6 -- 1.0 | **Cannot drop below 0.6** |
| 🎉 Affirmation | 0.6 -- 1.0 | **Cannot drop below 0.6** |
| 🏛️ Wisdom | 0.9 -- 1.0 | **Near-permanent** |

</details>

<br>

### Self-Improving Loop

```mermaid
flowchart LR
    A["🔧 Tool call fails"] --> B["🔄 Retry"]
    B --> C["✅ Succeeds"]
    C --> D["🧠 Extract learning"]
    D --> E["💾 Store"]
    E --> F{"N hits?"}
    F -->|Yes| G["⬆️ Promote to<br>permanent prompt"]
    F -->|No| H["📊 Track"]
    H --> F

    style A fill:#e74c3c,color:#fff
    style C fill:#2ecc71,color:#fff
    style G fill:#9b59b6,color:#fff
```

<br>

---

<br>

## 🛡️ Security

> [!WARNING]
> Stronghold assumes **adversarial users, adversarial LLMs, and adversarial tool results**. Every trust boundary is defended.

<br>

<table>
<tr>
<td width="33%">

#### 🛡️ Warden
**4-Layer Threat Detection**

Runs at user input and tool results.

| Layer | Technique |
|-------|-----------|
| L1 | Regex (20+ patterns) ✅ |
| L2 | Heuristics ⚠️ |
| L2.5 | Semantic poisoning ⚠️ |
| L3 | LLM classifier ⚠️ |

Plus: NFKD normalization, ReDoS protection, 10KB scan window.

</td>
<td width="33%">

#### 🔒 Sentinel
**Policy Enforcement**

LiteLLM guardrail (pre + post call).

- ✅ Schema validation + repair
- 🔑 Per-agent tool permissions
- 📐 Token optimization
- 🚫 PII filter (15 patterns)
- 📋 Audit logging

</td>
<td width="33%">

#### 🚪 The Gate
**Input Processing**

- Strip zero-width chars
- Normalize unicode
- Escape injection fragments
- Warden scan
- Sufficiency check
- Optional query improver

</td>
</tr>
</table>

<br>

> [!TIP]
> See [SECURITY.md](SECURITY.md) for the full threat model, competitive analysis, and Warden benchmarks (213-sample adversarial dataset: 88 social engineering + 125 benign real-world).

<br>

---

<br>

## 📋 Architecture Decision Records

31 ADRs document the Kubernetes deployment design.

<table>
<tr>
<td align="center"><strong><a href="docs/adr/ADR-K8S-001-namespace-topology.md">001</a></strong><br><sub>🏗️ Namespace<br>Topology</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-003-secrets-approach.md">003</a></strong><br><sub>🔑 Pluggable<br>Secrets</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-004-networkpolicy-posture.md">004</a></strong><br><sub>🚧 Default-Deny<br>NetworkPolicy</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-013-hybrid-execution-model.md">013</a></strong><br><sub>⚡ Hybrid<br>Execution</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-018-per-user-credential-vault.md">018</a></strong><br><sub>🔐 Per-User<br>Vault</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-020-mcp-server-gateway-orchestrator.md">020</a></strong><br><sub>🔌 MCP<br>Gateway</sub></td>
<td align="center"><strong><a href="docs/adr/ADR-K8S-028-stronghold-as-a2a-peer.md">028</a></strong><br><sub>🤝 A2A<br>Peer</sub></td>
</tr>
</table>

<details>
<summary>&nbsp;📋&nbsp;&nbsp;<b>All 31 ADRs</b></summary>

<br>

| # | Title | Summary |
|---|-------|---------|
| [001](docs/adr/ADR-K8S-001-namespace-topology.md) | Namespace topology | Four namespace classes for trust boundary isolation |
| [002](docs/adr/ADR-K8S-002-rbac-boundary.md) | RBAC boundary | ServiceAccount and Role scopes per-namespace |
| [003](docs/adr/ADR-K8S-003-secrets-approach.md) | Secrets approach | Pluggable backend (k8s / sealed-secrets / eso / vault) |
| [004](docs/adr/ADR-K8S-004-networkpolicy-posture.md) | NetworkPolicy posture | Default-deny with explicit allow matrix |
| [005](docs/adr/ADR-K8S-005-warden-topology.md) | Warden topology | In-process for v0.9 with lift-out plan |
| [006](docs/adr/ADR-K8S-006-runtime-okd.md) | Runtime selection | OKD single-node as reference runtime |
| [007](docs/adr/ADR-K8S-007-distro-compatibility-matrix.md) | Distro compatibility | Tier-1: OKD/OCP; Tier-2: k3s, RKE2, cloud |
| [008](docs/adr/ADR-K8S-008-prod-dev-isolation.md) | Prod/dev isolation | Eight non-negotiable isolation rules |
| [009](docs/adr/ADR-K8S-009-migration-sequence.md) | Migration sequence | Phased rollout with rollback at every step |
| [010](docs/adr/ADR-K8S-010-storage-pluggability.md) | Storage pluggability | StorageClass-pluggable (local-path, NFS, CSI, cloud) |
| [011](docs/adr/ADR-K8S-011-secrets-provider-pluggability.md) | Secrets provider pluggability | Helm-template plumbing for four backends |
| [012](docs/adr/ADR-K8S-012-crc-sandbox.md) | CRC sandbox | On-demand CodeReady Containers for validation |
| [013](docs/adr/ADR-K8S-013-hybrid-execution-model.md) | Hybrid execution | Conversational (in-process) + agentic (per-mission pods) |
| [014](docs/adr/ADR-K8S-014-six-tier-priority-system.md) | Six-tier priority | P0-P5 spanning routing, scheduling, eviction |
| [015](docs/adr/ADR-K8S-015-priority-tier-eviction-order.md) | Eviction order | PriorityClass values and eviction rationale |
| [016](docs/adr/ADR-K8S-016-gitops-controller.md) | GitOps controller | OpenShift GitOps, manual sync, no auto-correct |
| [017](docs/adr/ADR-K8S-017-architecture-diagram-pipeline.md) | Diagram pipeline | Generated SVGs + hand-authored D2 |
| [018](docs/adr/ADR-K8S-018-per-user-credential-vault.md) | Per-user credential vault | OpenBao with K8s auth, per-user paths |
| [019](docs/adr/ADR-K8S-019-tool-policy-layer.md) | Tool policy layer | Casbin per-tool-call and per-task gates |
| [020](docs/adr/ADR-K8S-020-mcp-server-gateway-orchestrator.md) | MCP roles | Server, gateway, and orchestrator |
| [021](docs/adr/ADR-K8S-021-tool-catalog.md) | Tool catalog | Python decorator API, multi-tenant, semver |
| [022](docs/adr/ADR-K8S-022-skill-catalog.md) | Skill catalog | Markdown + YAML frontmatter, hot reload |
| [023](docs/adr/ADR-K8S-023-resource-catalog.md) | Resource catalog | URI-addressable state with vault injection |
| [024](docs/adr/ADR-K8S-024-mcp-transport-auth-discovery.md) | MCP transport/auth | HTTP+SSE, OAuth 2.0, per-user identity |
| [025](docs/adr/ADR-K8S-025-sandboxed-primitive-mcp-guests.md) | Sandboxed MCP guests | Three use cases for guest server pods |
| [026](docs/adr/ADR-K8S-026-sandbox-pod-catalog.md) | Sandbox pod catalog | Six templates with security profiles |
| [027](docs/adr/ADR-K8S-027-agent-catalog.md) | Agent catalog | A2A Agent Cards, trust-tier assignment |
| [028](docs/adr/ADR-K8S-028-stronghold-as-a2a-peer.md) | A2A peer | Tasks/create, get, stream, cancel |
| [029](docs/adr/ADR-K8S-029-a2a-guest-peers.md) | A2A guest peers | Outbound delegation with trust gating |
| [030](docs/adr/ADR-K8S-030-task-acceptance-policy.md) | Task acceptance | Casbin at A2A boundary, budget enforcement |
| [031](docs/adr/ADR-K8S-031-builder-capabilities.md) | Builder capabilities | Forge: skills, strategies, MCP scaffolds |

See [`docs/adr/README.md`](docs/adr/README.md) for reading order.

</details>

<br>

---

<br>

## 🧭 Design Principles

<table>
<tr>
<td width="50%">

**💰 Use the cheapest reliable tool**<br>
<sub>Deterministic code > cheap model > strong model > human.</sub>

**🎮 Runtime is in charge**<br>
<sub>The LLM proposes; the runtime validates, bounds, and may reject.</sub>

**🔒 All input is untrusted**<br>
<sub>User input AND tool results get Warden scans.</sub>

**🧹 Memory must forget**<br>
<sub>Decay without reinforcement. Weight floors for wisdom/regrets.</sub>

</td>
<td width="50%">

**✅ Evaluate inline**<br>
<sub>Validation at every boundary during execution, not post-hoc.</sub>

**📐 Budget context windows**<br>
<sub>Priority-ordered assembly with hard token limits.</sub>

**⚖️ Autonomy is a tradeoff**<br>
<sub>Every capability needs bounds (max rounds, budgets, timeouts).</sub>

**🧱 Multi-agent for isolation only**<br>
<sub>Add agents for permission, trust, or strategy isolation, not aesthetics.</sub>

</td>
</tr>
</table>

<br>

---

<br>

## 📊 Observability

<table>
<tr>
<td align="center">📝<br><strong>Prompts</strong><br><sub>PostgreSQL<br>(versioned, labeled)</sub></td>
<td align="center">📈<br><strong>Traces</strong><br><sub>Arize Phoenix<br>or Enterprise</sub></td>
<td align="center">📡<br><strong>Telemetry</strong><br><sub>LiteLLM callbacks<br>→ Phoenix/Arize</sub></td>
<td align="center">📋<br><strong>Audit</strong><br><sub>PostgreSQL<br>(org-scoped)</sub></td>
<td align="center">🪵<br><strong>Logging</strong><br><sub>dictConfig → stdout<br>(run_id-tagged)</sub></td>
<td align="center">🖥️<br><strong>Dashboard</strong><br><sub>6 castle-themed<br>pages</sub></td>
</tr>
</table>

<br>

---

<br>

## 📚 Documentation

| | Document | Purpose |
|-|----------|---------|
| 📐 | [ARCHITECTURE.md](ARCHITECTURE.md) | Full system design -- **read first** |
| 🛡️ | [SECURITY.md](SECURITY.md) | Threat model, 4-layer Warden, competitive analysis |
| 🗺️ | [ROADMAP.md](ROADMAP.md) | Phase-by-phase release plan through v2.0 |
| 📋 | [BACKLOG.md](BACKLOG.md) | Completed work, known issues, red team findings |
| 🎓 | [ONBOARDING.md](ONBOARDING.md) | Codebase patterns, import paths, test patterns |
| 📋 | [docs/adr/](docs/adr/) | 31 Kubernetes architecture decision records |
| 🛡️ | [docs/blue-team-training-spec.md](docs/blue-team-training-spec.md) | Blue team training specification |
| 🤖 | [CLAUDE.md](CLAUDE.md) | Development guidelines for Claude Code |

<br>

---

<div align="center">

<br>

[Apache 2.0 License](LICENSE)

<br>

</div>
