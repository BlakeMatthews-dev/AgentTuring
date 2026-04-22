# Stronghold Helm Chart — Complete Reference for AKS Deployment

## Chart Metadata

- **Chart:** `deploy/helm/stronghold/`, name `stronghold`, version 0.9.0-pr6
- **appVersion:** 0.9.0-pr6
- **kubeVersion:** >=1.29.0-0
- **License:** Apache 2.0

---

## 1. Files and Purpose

### Top-level

| File | Purpose |
|---|---|
| `Chart.yaml` | Chart metadata, version 0.9.0-pr6 |
| `values.yaml` | Base defaults (everything disabled/minimal) |
| `values-vanilla-k8s.yaml` | Overlay: disables OpenShift, enables RBAC + PriorityClasses |
| `values-aks.yaml` | Overlay: Azure Workload Identity, managed-csi storage, nginx ingress, Entra ID auth, HPA |
| `values-prod-homelab.yaml` | Overlay: k3s single-node, local registry at 10.10.42.100:5000, Calico NetworkPolicy |
| `files/litellm-proxy-config.yaml` | LiteLLM model config (mounted via ConfigMap) |

### Templates — Workloads (5 Deployments + 1 StatefulSet)

| Template | Kind | Namespace | Priority | Gate |
|---|---|---|---|---|
| `deployment-stronghold.yaml` | Deployment | release NS | P0 | always |
| `deployment-litellm.yaml` | Deployment | release NS | P1 | always |
| `deployment-phoenix.yaml` | Deployment | release NS | P1 | always |
| `deployment-mcp-github.yaml` | Deployment | stronghold-mcp | P1 | `mcp.github.enabled AND mcp.github.devMode` |
| `deployment-mcp-dev-tools.yaml` | Deployment | stronghold-mcp | P1 | `mcp.devTools.enabled` |
| `statefulset-postgres.yaml` | StatefulSet | release NS | P1 | always |
| `vault-deployment.yaml` | Deployment + NS + SA + ConfigMap + Service + NetworkPolicy | stronghold-system | — | `vault.enabled` |

### Templates — Services (6)

| Template | Port | Exposes |
|---|---|---|
| `service-stronghold.yaml` | 8100 | API |
| `service-litellm.yaml` | 4000 | LLM proxy |
| `service-phoenix.yaml` | 6006 | Observability UI + OTEL collector |
| `service-postgres.yaml` | 5432 | Database |
| `service-mcp-github.yaml` | 3000 | GitHub MCP (dev mode only) |
| `service-mcp-dev-tools.yaml` | 8300 | Dev tools MCP |

### Templates — Ingress / Routes (6, mutually exclusive)

| Template | Gate |
|---|---|
| `ingress-stronghold.yaml` | `NOT openshift.enabled AND ingressRoutes.enabled` |
| `ingress-litellm.yaml` | same |
| `ingress-phoenix.yaml` | same |
| `route-stronghold.yaml` | `openshift.enabled` |
| `route-litellm.yaml` | same |
| `route-phoenix.yaml` | same |

### Templates — RBAC (3 Role+RoleBinding pairs)

| Template | ServiceAccount | Namespace | Permissions |
|---|---|---|---|
| `rbac-stronghold-api.yaml` | stronghold-api | release NS | Read-only: configmaps, secrets, services, endpoints, pods. Read-write: leases (leader election) |
| `rbac-mcp-deployer.yaml` | mcp-deployer | stronghold-mcp | Full CRUD: deployments, services, configmaps, secrets. Read: pods, pods/log. Routes (OpenShift only) |
| `rbac-postgres.yaml` | postgres | release NS | Minimal |

### Templates — ServiceAccounts (5)

`serviceaccount-stronghold-api.yaml`, `serviceaccount-mcp-deployer.yaml`, `serviceaccount-postgres.yaml`, `serviceaccount-litellm.yaml`, `serviceaccount-phoenix.yaml` — each renders annotations from `serviceAccounts.<name>.annotations` (used for Azure Workload Identity).

### Templates — Network Policies (6)

| Template | Gate | Policy |
|---|---|---|
| `networkpolicy-default-deny.yaml` | `networkPolicy.enabled` | Deny all ingress + egress for entire namespace |
| `networkpolicy-stronghold-api.yaml` | same | Ingress: from ingress controller. Egress: postgres, litellm, phoenix, MCP namespace, DNS |
| `networkpolicy-litellm.yaml` | same | Ingress: from stronghold-api only. Egress: postgres, DNS, external HTTPS (0.0.0.0/0 minus RFC1918, or specific CIDRs) |
| `networkpolicy-phoenix.yaml` | same | OTEL ingress from stronghold-api |
| `networkpolicy-postgres.yaml` | same | From stronghold-api + litellm + phoenix only |
| `networkpolicy-mcp.yaml` | same | MCP namespace policies |

### Templates — Other

| Template | Purpose | Gate |
|---|---|---|
| `hpa-stronghold-api.yaml` | HPA for API pods | `autoscaling.strongholdApi.enabled` |
| `hpa-litellm.yaml` | HPA for LiteLLM pods | `autoscaling.litellm.enabled` |
| `pdb-stronghold-api.yaml` | PDB (minAvailable: 1) | `podDisruptionBudgets.enabled AND replicas > 1` |
| `pdb-litellm.yaml` | PDB (minAvailable: 1) | same pattern |
| `priorityclass-p0..p5.yaml` | 6 PriorityClasses (P0=1000000 down to P5=100000) | `priorityClasses.create` |
| `scc-binding-stronghold-api.yaml` | OpenShift SCC binding | `openshift.enabled` |
| `scc-binding-mcp-deployer.yaml` | OpenShift SCC binding | same |
| `namespace.yaml` | Optional namespace creation | `namespace.create` |
| `extra-namespaces.yaml` | stronghold-mcp + stronghold-data | `extraNamespaces.create` |
| `configmap-stronghold.yaml` | App config (server port, DB URL, router URL) | always |
| `configmap-litellm.yaml` | LiteLLM model config from `files/` | always |
| `configmap-postgres-init.yaml` | Init SQL scripts | always |
| `secret-postgres-auth.yaml` | Auto-generated 32-char password (reused on upgrade via lookup) | `NOT postgresql.existingSecret` |
| `secret-litellm-env.yaml` | Stub API keys (all empty) | `litellmProxy.createStubSecret` |
| `_helpers.tpl` | Template functions: fullname, labels, image composition, SA names, OpenShift gate |
| `NOTES.txt` | Post-install instructions |

---

## 2. Resource Requests and Limits (AKS overlay)

| Workload | CPU req | Mem req | CPU limit | Mem limit | Replicas |
|---|---|---|---|---|---|
| stronghold-api | 100m | 192Mi | 1 | 512Mi | 1 (HPA to 4) |
| litellm | 100m | 256Mi | 1 | 1Gi | 1 |
| postgres | 100m | 256Mi | 1 | 2Gi | 1 (StatefulSet) |
| phoenix | 50m | 128Mi | 500m | 1Gi | 1 |
| mcp-github | 100m | 128Mi | 500m | 512Mi | 1 (dev only) |
| mcp-dev-tools | 100m | 128Mi | 500m | 512Mi | 1 |
| vault | 100m | 128Mi | 500m | 256Mi | 1 (optional) |
| **Total (core 4)** | **350m** | **832Mi** | | | |

---

## 3. Volumes and Storage

| Workload | Volume | Type | Size | Mount |
|---|---|---|---|---|
| postgres | `data` | PVC (volumeClaimTemplate) | 8Gi (AKS) / 20Gi (default) | `/var/lib/postgresql/data` |
| postgres | `init-scripts` | ConfigMap | — | `/docker-entrypoint-initdb.d` (ro) |
| stronghold-api | `config` | ConfigMap | — | `/app/config` (ro) |
| stronghold-api | `tmp` | emptyDir | 64Mi | `/tmp` |
| stronghold-api | `mcp-deployer-socket` | emptyDir (Memory) | 16Mi | `/run/stronghold` (sidecar IPC, if enabled) |
| litellm | `config` | ConfigMap | — | `/app/config` (ro) |
| litellm | `tmp` | emptyDir | 128Mi | `/tmp` |
| phoenix | `phoenix-tmp` | emptyDir | 512Mi | `/tmp` |
| mcp-github | `tmp` | emptyDir | 64Mi | `/tmp` |
| mcp-dev-tools | `workspace` | PVC (optional) or emptyDir | 1Gi | `/workspace` |
| vault | `vault-data` | emptyDir (use PVC for prod) | — | `/vault/data` |

**StorageClass:** `managed-csi` on AKS (Azure Disk CSI, default on 1.29+). Blank in base values (uses cluster default).

---

## 4. Environment Variables and Secrets

### stronghold-api

| Var | Source | Value |
|---|---|---|
| `DATABASE_URL` | Constructed in template | `postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@<release>-postgres:5432/$(POSTGRES_DB)` |
| `LITELLM_URL` | Constructed | `http://<release>-litellm:4000` |
| `PHOENIX_COLLECTOR_ENDPOINT` | Constructed | `http://<release>-phoenix:6006` |
| `STRONGHOLD_CONFIG` | values | `/app/config/example.yaml` |
| `MCP_DEPLOYER_SOCKET` | values (if sidecar enabled) | `/run/stronghold/mcp-deployer.sock` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `envFrom: secretRef` | From `secret-postgres-auth.yaml` or `existingSecret` |

### litellm

| Var | Source |
|---|---|
| `DATABASE_URL` | Constructed (same pattern, shared postgres) |
| `POSTGRES_*` | envFrom: postgres credentials secret |
| Provider API keys | envFrom: `litellm-secrets` (stub or ESO-managed) |

Keys in stub secret: `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `TOGETHER_API_KEY`

### phoenix

| Var | Source |
|---|---|
| `PHOENIX_SQL_DATABASE_URL` | Constructed (`postgresql://...@<release>-postgres:5432/phoenix`) |
| `PHOENIX_WORKING_DIR` | Hardcoded `/tmp/phoenix` |
| `POSTGRES_*` | envFrom: postgres credentials secret |

### mcp-github

| Var | Source |
|---|---|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | `secretKeyRef` from `github-pat` secret, key `token` |

### Secrets handling

- **Postgres password:** Auto-generated 32-char `randAlphaNum` on first install, persisted via `lookup` on upgrades. Production: use `postgresql.existingSecret` with sealed-secrets or ESO.
- **LiteLLM keys:** Stub secret with empty values. Production: disable `createStubSecret`, provide via ESO to Azure Key Vault.
- **No secrets in ConfigMaps.** No secrets in env values (all via secretRef/envFrom).

---

## 5. Ingress Config (AKS)

- **Class:** `nginx` (default in AKS overlay). Override to `azure-application-gateway` for AGIC.
- **Hosts:** `stronghold.example.com`, `litellm.internal.example.com`, `phoenix.internal.example.com` (override via `--set`)
- **TLS:** Not configured in templates (add via annotations or cert-manager)
- **OpenShift:** Uses Routes with edge TLS termination instead (mutually exclusive gate)

---

## 6. Node Selectors, Tolerations, Affinity

**None.** No `nodeSelector`, `tolerations`, or `affinity` in any template or values file. Pods schedule wherever the scheduler puts them.

---

## 7. Values Overlays — Which to Use

| Scenario | Command |
|---|---|
| **AKS** | `-f values-vanilla-k8s.yaml -f values-aks.yaml` |
| **EKS** | `-f values-vanilla-k8s.yaml` (values-eks.yaml planned, not yet created) |
| **GKE** | `-f values-vanilla-k8s.yaml` (values-gke.yaml planned, not yet created) |
| **OpenShift/OKD** | Base values.yaml with `openshift.enabled: true` |
| **Homelab (k3s)** | `-f values-prod-homelab.yaml` |

AKS overlay is the only cloud overlay that exists today.

---

## 8. Architecture Notes

### Request flow

```
POST /v1/chat/completions (or via OpenWebUI -> Pipelines -> Stronghold)
  |
  +- Auth: JWT validation (Entra ID / Keycloak / static key)
  +- Gate: sanitize input (unicode normalization, zero-width strip)
  +- Warden scan Layer 1-3 (regex -> heuristic -> optional LLM): 2-10ms typical
  |
  +- Classifier: keyword scoring -> LLM fallback if score < 3.0
  |   Keyword-only: 1-3ms. LLM fallback (~30% of requests): +100-200ms
  |
  +- Session stickiness: reuse previous agent for same session_id
  +- If ambiguous -> Arbiter (clarification, then re-route)
  +- Intent registry: task_type -> agent_name lookup
  |
  +- agent.handle():
  |   +- Context builder: soul prompt + learnings (max 20) + tools + token budget
  |   +- Strategy.reason():
  |   |   +- direct:       1 LLM call, return
  |   |   +- react:        LLM -> tool -> LLM -> tool (max 3 rounds)
  |   |   +- plan_execute: plan -> subtask loop (max 5 phases x 3 retries)
  |   |   +- delegate:     classify -> route to sub-agent
  |   +- Warden scan on every tool result before re-injection
  |   +- PII redaction on tool results (13 regex patterns)
  |   +- Learning extraction from tool history (fail->succeed patterns)
  |
  +- Return response
```

### What each pod actually does

**stronghold-api** — The entire Stronghold runtime. FastAPI (uvicorn), fully async. Classifier, router, all agents, Warden, context builder, learning extraction — all in-process. This is the only pod that does real work. Every other pod is infrastructure it calls.

**litellm** — HTTP proxy. Receives `POST /chat/completions` from stronghold-api, forwards to the configured LLM provider (Azure OpenAI, Anthropic, Mistral, etc.), returns the response. Also serves as MCP gateway and tracks spend in postgres. Near-zero local compute.

**postgres** — Single instance, shared by stronghold (agents, learnings, sessions, audit, prompts, permissions, tournaments), litellm (spend tracking, Prisma), and phoenix (OTEL spans). pgvector extension for embedding search (episodic memory, knowledge RAG).

**phoenix** — Receives OTEL spans from stronghold-api over HTTP. Stores in postgres (phoenix database). Provides a web UI on :6006 for trace inspection. Small team observability — replace with Arize Enterprise for multi-tenant RBAC.

### Agent resource profiles

Standard agents (Arbiter, Ranger, Scribe) are **pure async I/O**. They build a context, call `await llm_client.complete()`, wait for the response, maybe call a tool (another HTTP call), and return. Peak memory per request: ~200 KB. CPU: near zero (waiting on network).

Heavy agents (Artificer, Forge, Warden-at-Arms) spawn **real subprocesses**:

- **Artificer**: `pytest`, `mypy --strict`, `ruff check`, `bandit` as child processes via `asyncio.create_subprocess_shell()`. pytest with 550+ tests: 200-400 MB. mypy: 100-300 MB. Total spike: ~800 MB.
- **Forge**: security scanner + schema validator + test executor — similar pattern.
- **Warden-at-Arms**: API calls, runbook execution — may spawn shell commands.

These heavy agents belong in separate deployments with their own resource limits. The current chart runs everything in one stronghold-api pod — sized for chat (512Mi limit), not for Artificer.

### Agent roster

| Agent | Strategy | Tools | Trust | Purpose |
|---|---|---|---|---|
| **Arbiter** | delegate | none | T0 | Triages ambiguous requests. Cannot act directly. |
| **Ranger** | react | web_search, database_query, knowledge_search | T1 (untrusted output) | Read-only information retrieval. Output always Warden-scanned. |
| **Artificer** | plan_execute (custom) | file_ops, shell, test_runner, lint_runner, git | T1 | Code/engineering. Sub-agents: planner, coder, reviewer, debugger. |
| **Scribe** | plan_execute (custom) | file_ops | T1 | Writing/creative. Committee: researcher, drafter, critic, advocate, editor. |
| **Warden-at-Arms** | react | ha_control, api_call, runbook_execute | T1 elevated | Real-world interaction. API surface discovery on init. |
| **Forge** | react | file_ops, scanner, schema_validator, test_executor | T1 elevated | Creates tools and agents. Output starts at skull tier. |

### Protocol-driven DI

Every external dependency is behind a protocol in `src/stronghold/protocols/`. The DI container (`container.py`) wires implementations at startup:

- Tests use fakes from `tests/fakes.py` (InMemoryLearningStore, FakeLLMClient, etc.)
- Swap Keycloak for Entra ID by changing config, not code
- LiteLLM can be replaced with direct provider SDKs

Key protocols: `LLMClient`, `LearningStore`, `AuthProvider`, `IntentClassifier`, `ModelRouter`, `QuotaTracker`, `PromptManager`, `TracingBackend`, `ToolRegistry`, `SkillRegistry`.

### Security layers

**Warden** (threat detection) — Runs at exactly two points: user input and tool results. Three layers: regex patterns (sub-ms), heuristic scoring (1-3ms), optional LLM classification (100-200ms, only if ambiguous). Verdict: clean/sanitized/blocked. Cannot call tools or access memory.

**Sentinel** (policy enforcement) — LiteLLM guardrail plugin (pre-call + post-call hooks). Pre-call: schema validation + repair on tool arguments. Post-call: Warden scan on tool results, token optimization, PII filtering, audit logging.

### Trust tiers

| Tier | Name | Description |
|---|---|---|
| Skull | In Forge | Under construction. Cannot be used. |
| T3 | Forged | Passed Forge QA. Sandboxed. Read-only tools only. |
| T2 | Community | Marketplace install or operator-approved. Standard policies. |
| T1 | Installed | Operator-vetted. Full tool access per agent config. |
| T0 | Built-in | Shipped with Stronghold. Core trust. |

Promotion: Skull -> T3 (Forge QA) -> T2 (N uses, no Warden flags) -> T1 (operator approval). Never auto-promotes to T0.

### Memory system

- **Learnings**: Per-agent corrections from tool failures. Capped at 10,000/org. Keyword + embedding hybrid search. Auto-promote after N successful injections.
- **Episodic memory**: 7-tier weighted (Observation -> Wisdom). Regrets (>=0.6) and wisdom (>=0.9) structurally unforgettable. pgvector.
- **Sessions**: Conversation history in postgres, scoped by user + session_id.
- **Prompts**: Versioned text blobs in postgres. Production/staging labels. Hot-reload via LISTEN/NOTIFY.

### Memory scopes

| Scope | Visibility |
|---|---|
| `global` | All agents, all users |
| `team` | Agents in the same domain |
| `user` | All agents, one user |
| `agent` | One agent only |
| `session` | One conversation only |

### Multi-tenant isolation

Per-tenant K8s namespace. Each gets own LiteLLM API keys, own Arize project/space, memory scoped by `tenant_id` in shared postgres (or separate postgres per namespace). Network policies prevent cross-namespace traffic.

### Auth (Entra ID on AKS)

JWT validation against `https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration`. Extracts app roles from `roles` claim. Config-driven role mapping:

- `Stronghold.Admin` -> admin (all tools, all agents)
- `Stronghold.Engineer` -> engineer (code + search + writing agents)
- `Stronghold.Operator` -> operator (device control, runbooks)
- `Stronghold.Viewer` -> viewer (read-only search)

Static API key fallback always available for service-to-service.

### Orchestrator concurrency

Defaults to 3 concurrent requests. Priority queue by tier (P0-P5). Session-sticky LRU cache (10,000 sessions). Since most time is LLM latency, effective throughput is much higher than 3.

### Model routing

Scarcity-based formula: `score = quality^(qw*p) / (1/ln(remaining_tokens))^cw`. Cost rises smoothly as provider tokens are consumed. Task-type-aware speed bonuses (voice gets speed weight, code gets quality weight). Filter by tier/quota/status, score by quality/speed/strength, select best model.

### Observability

| Concern | Backend |
|---|---|
| Prompt management | PostgreSQL (stronghold.prompts) |
| Traces + scoring (small team) | Arize Phoenix (OSS) |
| Traces + scoring (enterprise) | Arize Enterprise |
| LLM call telemetry | LiteLLM callbacks -> Phoenix or Arize |
| Audit trail | PostgreSQL (stronghold.audit_log) |

Every request is a trace. Every boundary crossing is a span. OTEL-native.

### What's NOT in the chart yet

- Separate Artificer/Forge deployment (heavy agent isolation)
- Redis (optional for distributed rate limiting — in-memory fallback exists)
- Celery/task queue (InMemoryTaskQueue by default)
- values-eks.yaml, values-gke.yaml (referenced in ADR-K8S-007, not created)
- TLS in ingress templates (add via cert-manager annotations)
- Node selectors, tolerations, or affinity rules
- Cluster autoscaler configuration (AKS cluster-level, documented in INSTALL-AKS.md)

---

## 9. Addendum: Builder Pipeline and Automation Loops

Stronghold has an autonomous development pipeline that picks up GitHub issues, decomposes them, writes tests, implements code, reviews PRs, and auto-fixes CI failures. This is a chain of specialized agents orchestrated by the Reactor (1000Hz event loop) and the BuilderPipeline (`src/stronghold/orchestrator/pipeline.py`).

### The pipeline (issue to merge)

```
GitHub issue (labeled "builders")
  |
  +- Backlog Scanner (reactor trigger, every 5 min)
  |   Polls GitHub API for open issues with "builders" label
  |   Triages: atomic (small) vs decomposable (epic)
  |   Labels issue with "atomic" or "needs-decomposition" + "in-progress"
  |   Max 3 concurrent issues
  |
  +- Stage 1: QUARTERMASTER (decompose)
  |   Agent: quartermaster (not yet a shipped agent — referenced in pipeline)
  |   Skipped if issue is atomic
  |   Decomposes epics into atomic sub-issues with acceptance criteria
  |   Needs: GitHub API access, LLM
  |
  +- Stage 2: ARCHIE (scaffold)
  |   Agent: archie (referenced as "archie" in pipeline, maps to Frank's role)
  |   Creates protocols in src/stronghold/protocols/
  |   Adds fakes to tests/fakes.py
  |   Creates empty module files with docstrings
  |   Updates ARCHITECTURE.md
  |   Does NOT write implementation code
  |   Needs: file_ops, shell, git, workspace, LLM, GitHub API
  |
  +- Stage 3: MASON (implement)
  |   Agent: mason
  |   8-phase TDD pipeline (see below)
  |   Writes tests first, then implementation
  |   Runs quality gates: pytest, ruff, mypy --strict, bandit
  |   Creates PR when all gates pass
  |   Needs: file_ops, shell, run_pytest, run_ruff, run_mypy, run_bandit,
  |          git, github, workspace, LLM
  |   Resource spike: subprocess spawning (pytest 200-400MB, mypy 100-300MB)
  |
  +- Stage 4: AUDITOR (review)
  |   Agent: auditor
  |   Reviews PR diff against project standards
  |   Posts structured comments with ViolationCategory tags
  |   Output feeds into RLHF loop (learnings stored in Mason's memory)
  |   Does NOT modify code — read-only
  |   Needs: github_cli, file_ops, LLM
  |
  +- Stage 5: GATEKEEPER (cleanup)
      Agent: gatekeeper
      Skipped if Auditor review is clean
      Fixes violations found by Auditor
      Runs ruff --fix, ruff format, mypy fixes
      Pushes to existing PR branch (does NOT create new PR)
      Needs: file_ops, shell, quality gate tools, git, LLM
```

Each stage has a 10-minute timeout. Output from one stage is passed as context to the next (truncated to 2000 chars).

### Agent details

#### Frank (The Architect)

| | |
|---|---|
| **File** | `agents/frank/agent.yaml` + `SOUL.md` |
| **Strategy** | react (max 10 rounds) |
| **Role** | Analyze issues, design solutions, write Gherkin acceptance criteria, produce diagnostic artifact for Mason |
| **Tools** | github, file_ops, shell, workspace, run_pytest |
| **Priority** | P5 (builders tier) |
| **Model** | auto (fallback: gemini-2.5-pro, mistral-large) |
| **Does NOT** | Write implementation code. That is Mason's job. |
| **Output** | Architecture plan, Gherkin scenarios, failing test suite, diagnostic artifact (execution mode, prior failures, lessons, coverage expectation) |
| **Infrastructure needs** | Git clone + worktree (/workspace volume), GitHub API token, LLM provider, postgres (learnings) |

#### Mason (The Bricklayer)

| | |
|---|---|
| **File** | `agents/mason/agent.yaml` + `SOUL.md` + `RULES.md` |
| **Strategy** | builders_learning (custom, 8-phase) |
| **Role** | Persistent autonomous code generation with evidence-driven TDD |
| **Tools** | file_ops, shell, run_pytest, run_ruff_check, run_ruff_format, run_mypy, run_bandit, git, github |
| **Priority** | P5 (builders tier) |
| **Max rounds** | 50 (across all 8 phases) |
| **Model** | auto (fallback: gemini-2.5-pro, mistral-large), temp 0.2 |
| **Does NOT** | Write code before Phase 7. Skip any phase. |

**Mason's 8 phases:**
1. **Acceptance criteria** — derive testable criteria from issue + Frank's diagnostic (max 3 rounds)
2. **Acceptance tests** — write failing tests for each criterion (max 5 rounds)
3. **Edge case tests** — boundary, adversarial, concurrency, multi-tenant (max 3 rounds)
4. **Style tests** — protocol compliance, type safety, naming, security (max 2 rounds)
5. **Code smell tests** — DI violations, private field access, bundled concerns (max 2 rounds)
6. **Test review** — adversarial review of ALL tests, tighten until unbreakable (max 5 rounds)
7. **Implementation** — minimum code to pass all tests + quality gates (max 10 rounds)
8. **Post-review** — verify code solves the issue, check coverage, create PR (max 2 rounds)

**Infrastructure needs:**
- Git clone + worktree (/workspace volume, writable)
- GitHub API token (create PRs, post comments)
- LLM provider (50 tool calls/request, 8192 max tokens)
- Subprocess execution: pytest, ruff, mypy, bandit (each 100-400MB peak)
- Postgres (learnings store — reads prior feedback before each session)

**Resource impact:** Mason is the most expensive agent. A single issue pipeline run can make 50+ LLM calls and spawn dozens of quality gate subprocesses. Each subprocess (pytest, mypy) can spike to 200-400MB. This is why Mason should NOT share a pod sized for chat.

#### Auditor

| | |
|---|---|
| **File** | `agents/auditor/agent.yaml` + `SOUL.md` + `RULES.md` |
| **Strategy** | react (max 10 rounds) |
| **Role** | PR review. Structured comments with ViolationCategory tags. |
| **Tools** | github_cli, file_ops |
| **Priority** | P3 (backend support) |
| **Does NOT** | Modify code. Only reviews. |
| **Proactive** | `pr.opened` event trigger + cron every 30 min for unreviewed PRs |
| **RLHF output** | Findings are extracted into Learnings and stored in Mason's agent memory via FeedbackLoop |

**Infrastructure needs:** GitHub API token (read PR diffs, post review comments), LLM provider, postgres (learnings store for writing feedback).

#### Gatekeeper

| | |
|---|---|
| **File** | `.github/workflows/gatekeeper-review.yml` (CI) + pipeline stage (in-cluster) |
| **CI role** | GitHub App that auto-approves PRs when CI passes. Runs as a GitHub Actions workflow triggered by CI completion. |
| **Pipeline role** | Final cleanup stage — fixes Auditor-found violations, pushes to PR branch |
| **Does NOT** | Create new PRs. Only pushes to existing branches. |
| **CI needs** | GitHub App credentials (GATEKEEPER_APP_ID, GATEKEEPER_PRIVATE_KEY, GATEKEEPER_INSTALLATION_ID) |
| **Pipeline needs** | file_ops, shell, quality gate tools, git, LLM |

#### CI Autofix

| | |
|---|---|
| **File** | `.github/workflows/ci-autofix.yml` |
| **Role** | When CI fails on a PR, extracts failure details and creates a repair issue labeled `ci-autofix,builders` |
| **How** | GitHub Actions workflow triggered by CI failure. Posts failure log as PR comment. Creates GitHub issue with repair instructions for Mason. |
| **Needs** | GitHub token (create issues, post comments) |
| **Connection** | The repair issue gets the `builders` label, so the Backlog Scanner picks it up and routes it through the pipeline |

#### Quartermaster (planned, not yet a shipped agent)

Referenced in the pipeline as the decomposition stage. Breaks epics into atomic sub-issues. Currently handled by heuristics in the Backlog Scanner (checkbox detection, section count, body length). Will be a full agent that uses LLM to decompose complex issues.

### Reactor triggers (background loops)

These run inside the stronghold-api pod on the 1000Hz reactor loop:

| Trigger | Interval | What it does |
|---|---|---|
| `issue_backlog_scanner` | 5 min | Polls GitHub for `builders` issues, triages, dispatches through pipeline |
| `learning_promotion_check` | 60s | Checks if any learnings have enough hits to auto-promote to permanent prompt |
| `rate_limit_eviction` | 5 min | Evicts stale keys from in-memory rate limiter |
| `outcome_stats_snapshot` | 5 min | Logs task completion rates |
| `tournament_evaluation` | 10 min | Checks agent head-to-head scores for promotion |
| `canary_deployment_check` | 30s | Monitors canary skill deployments for promotion/rollback |
| `rlhf_feedback` | event | On `pr.reviewed` event, extracts learnings from Auditor output into Mason's memory |
| `mason_pr_review` | event | On `mason.pr_review_requested`, dispatches PR review-and-improve to Mason |
| `security_rescan` | event | On `security.rescan`, re-scans flagged content through Warden |
| `post_tool_learning` | event | On `post_tool_loop`, logs learning extraction opportunities from tool failures |

### RLHF feedback loop

```
Auditor reviews PR
  -> posts structured ViolationCategory comments
  -> emits "pr.reviewed" event
  -> reactor fires rlhf_feedback trigger
  -> ReviewFeedbackExtractor converts findings to Learning objects
  -> LearningStore.store() saves to Mason's agent-scoped memory
  -> InMemoryViolationTracker records metrics (trend, findings/PR)
  -> Next time Mason starts work, it reads these learnings first
```

Goal: zero review comments per PR over time. Mason learns from every rejection.

### Builders runtime (`src/stronghold/builders/`)

Shared infrastructure for the builder agents:

- **contracts.py** — Pydantic models: RunRequest, RunResult, ArtifactRef, StageEvent, WorkerStatus. Workers: frank, mason, auditor.
- **runtime.py** — BuildersRuntime: stateless stage dispatcher. Registers handlers per worker+stage, executes them, manages prompt templates and tool allowlists per stage.

### Workspace manager (`src/stronghold/tools/workspace.py`)

Git worktree isolation for Mason. Each issue gets its own worktree branched from main:

1. `create(issue_number)` — clones repo (once), creates worktree at `/workspace/issue-{N}`
2. Mason writes files, runs tests in the isolated worktree
3. `commit_and_push()` — stages, commits, pushes the branch
4. `cleanup()` — removes worktree

Needs the `/workspace` volume (writable, 1Gi+ for repo clone + worktrees).

### Infrastructure requirements for the full pipeline

| Requirement | Why |
|---|---|
| **GitHub API token** | Backlog scanner polls issues, Mason creates PRs, Auditor posts reviews, Gatekeeper approves |
| **GitHub App** (Gatekeeper) | Auto-approve PRs with a non-human identity (APP_ID, PRIVATE_KEY, INSTALLATION_ID) |
| **/workspace volume** (writable, 2Gi+) | Git clone + worktrees for Mason and Frank |
| **LLM provider** | Every agent makes LLM calls. Mason: 50+ calls per issue. Auditor: 10-20 per PR. |
| **Postgres** | Learnings, feedback metrics, outcome tracking |
| **Subprocess capacity** | Mason runs pytest, mypy, ruff, bandit — each can spike to 200-400MB |
| **k3s-runners** (CI) | GitHub Actions self-hosted runners for Gatekeeper and CI Autofix workflows |

### Deployment implications for AKS

The builder pipeline is the strongest argument for separating heavy agents into their own deployment:

| Component | Where it should run | Why |
|---|---|---|
| Backlog scanner + reactor triggers | stronghold-api pod | Lightweight — just HTTP polling + event evaluation |
| Frank, Auditor | stronghold-api pod (OK) | Mostly LLM calls + file reads. Low resource. |
| Mason, Gatekeeper (pipeline stage) | **Separate deployment** | Subprocess spawning (pytest 200-400MB, mypy 100-300MB). Needs /workspace volume. Will OOM in a 512Mi chat pod. |
| Gatekeeper (CI) | GitHub Actions runner | Runs as a workflow, not in-cluster |
| CI Autofix | GitHub Actions runner | Runs as a workflow, not in-cluster |

Recommended: a `stronghold-builders` Deployment with 1.5-2Gi memory limit, /workspace PVC, and the same image but configured to only accept P5 (builders) priority work. The chat pod stays small.
