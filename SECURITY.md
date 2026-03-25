# Stronghold Security Model

**Version:** 0.1.0 (pre-release)
**Last Updated:** 2026-03-28

Stronghold is an enterprise multi-tenant agent governance platform. Security is not a feature — it's the architecture. This document describes the threat model, mitigations, and how Stronghold compares to other agent platforms.

---

## Threat Model

Stronghold assumes:
- **Users are untrusted.** Every input is potentially hostile.
- **LLM output is untrusted.** Tool arguments may be hallucinated or adversarial.
- **Tool results are untrusted.** External APIs may return injected instructions.
- **Community skills are untrusted.** Marketplace content may contain backdoors.
- **Tenants are adversarial.** Org-A actively tries to access Org-B's data.
- **The network is hostile.** SSRF, metadata endpoint attacks, DNS rebinding.

---

## Defense-in-Depth Layers

### Layer 1: Gate (Input Processing)
- Sanitizes zero-width characters, BOM, Unicode directional markers
- Warden 5-layer scan pipeline (see Warden Architecture below)
- Request sufficiency analysis (persistent/supervised modes)
- 10KB scan window to prevent ReDoS on crafted long inputs

### Warden Architecture (5-Layer Threat Detection)

The Warden is Stronghold's core threat detection engine. It runs at both boundaries (user input AND tool results) with a layered pipeline:

| Layer | Name | Technique | Detection Rate | FP Rate | Blocks? |
|-------|------|-----------|---------------|---------|---------|
| **L1** | Regex Patterns | 20+ patterns: role hijacking, instruction override, emotion manipulation, tool injection, context stuffing, "forget" variations, temporal overrides | High on known attacks | ~0% | YES (hard block) |
| **L2** | Heuristics | Instruction density scoring (imperative verb ratio), base64 encoded payload detection, emotion/poisoning token density | Medium | ~0% | No (flag-and-warn) |
| **L2.5** | Semantic Tool Poisoning | Prescriptive language ("should", "has been granted") + dangerous action/sensitive object combinations. Code syntax exclusion prevents FP on source code. | **62.5% on zero-day attacks** | **0% on 11,957 real samples** | No (flag-and-warn) |
| **L3** | Few-Shot LLM Classifier | 10-example few-shot prompt (5 benign + 5 attack). Detects prescriptive vs descriptive language in tool results. Fail-open: returns "safe" on any error. | Highest (model-dependent) | Low | No (flag-and-warn) |
| **L1** | NFKD Normalization | Unicode NFKD normalization before ALL scans. Prevents fullwidth, Cyrillic, and combining character evasion. | N/A (preprocessing) | N/A | N/A |

**L1 blocks. L2-L3 flag-and-warn**: content is preserved with a warning banner, admin is notified, and the user gets an escalation link. This prevents false-positive blocking while maintaining visibility.

**Benchmarked against 213-sample adversarial dataset**: 88 social engineering attacks (disguised as code comments) + 125 benign real-world tool outputs. L2.5 alone catches 62.5% of attacks that L1+L2 miss entirely, with 0% false positives on production data from HA, CoinSwarm, and Conductor codebases.

### Layer 2: Sentinel (Policy Enforcement)
- Pre-call: schema validation + repair (fuzzy enum match, type coercion)
- Pre-call: permission check (RBAC via PermissionTable)
- Post-call: Warden scan on tool results (full 5-layer pipeline)
- Post-call: PII filter (API keys, IPs, emails, JWTs, connection strings, private keys)
- Post-call: token optimization (JSON compaction, truncation)
- Audit logging at every boundary crossing (with org_id + team_id)

### Layer 3: Identity & Tenant Isolation
- JWT auth: IdP-agnostic (Keycloak, Entra ID, Auth0, Okta)
- 5 identity kinds: User, Agent, ServiceAccount, InteractiveAgent, System
- org_id + team_id on every data access (learnings, outcomes, sessions, skills)
- on_behalf_of validation (cross-org forgery rejected)
- Session IDs namespaced by org/team/user
- Constant-time API key comparison (hmac.compare_digest)
- JWKS caching with non-blocking refresh (stale cache during refresh, no DoS)

### Layer 4: Skill Security
- YAML frontmatter + markdown body parsing with strict validation
- Security scan: exec/eval/subprocess/credentials/prompt injection patterns
- Unicode NFKD normalization before scanning (prevents Cyrillic lookalike bypass)
- Directional Unicode marker rejection (RTL/LTR override attacks)
- Trust tiers: T0 (built-in, immutable) → T1 (operator) → T2 (community) → T3 (forged)
- T0/T1 skills cannot be overwritten by marketplace or forge
- T0/T1 skills cannot be auto-mutated by learnings
- Forged skills start at T3 (sandboxed), never auto-promote to T0
- Path traversal protection (resolved path must stay within skills_dir)
- Symlink rejection in skill loader
- 50KB body size limit (prevents context window stuffing)
- Learning text scanned before skill mutation (prevents backdoor injection)

### Layer 5: Resource Protection
- Learning store capped at 10K entries with FIFO eviction (OOM protection)
- Tool argument size limit: 100KB (JSON bomb protection)
- Warden regex scan window: 10KB (ReDoS protection)
- Skill body size limit: 50KB
- SSRF blocklist: private networks, cloud metadata endpoints, loopback
- find_relevant returns max 10 results (context overflow protection)

---

## Competitive Security Analysis (March 2026)

The agent platform landscape has a serious security problem. Every major platform has documented critical vulnerabilities. Stronghold is designed to address the specific attack vectors that have been exploited in production across the industry.

### The Industry's Security Crisis

| Platform | Worst CVE | Root Default | Prompt Injection Defense | Multi-Tenant |
|----------|-----------|:------------:|:------------------------:|:------------:|
| **OpenClaw** | CVSS 8.8 (RCE via WebSocket) + 512 audit vulns | YES | None | None |
| **LangChain** | CVSS 9.3 "LangGrinch" (injection → RCE) | No | None (native) | Paid only |
| **Azure AI** | CVSS 10.0 (Entra ID cross-tenant) | No | Prompt Shields | Yes |
| **Bedrock** | 8 attack vectors + DNS exfil | No | Guardrails (degradable) | AWS account |
| **CrewAI** | CVSS 9.2 (leaked GitHub token) | No | None (65% exfil rate) | Paid only |
| **Cursor** | 5+ high-severity RCEs | No (but auto-exec) | Allowlist (bypassed) | N/A |
| **Claude Code** | CVSS 8.7 (RCE via project files) | User-level | Regex (bypassed 4x) | N/A |
| **Semantic Kernel** | Critical RCE (CVE-2026-26030) | No | YES (default encoding) | Azure only |
| **Pydantic AI** | SSRF (CVE-2026-25580) | No | None | None |
| **Stronghold** | **None (pre-release)** | **No** | **5-layer Warden + Gate** | **Core architecture** |

### Attack-by-Attack Comparison

#### Prompt Injection
| Platform | Defense | Known Bypasses |
|----------|---------|----------------|
| OpenClaw | None | N/A — wide open |
| LangChain | None native (LangSmith gateway optional) | LangGrinch: prompt → serialization → RCE |
| CrewAI | None | 65% data exfiltration success in research |
| Cursor | Command allowlist | Bypassed via shell builtins (export/typeset) |
| Claude Code | Regex blacklist | Bypassed 4+ times (CVE-2025-59536, CVE-2026-24052) |
| Bedrock | Guardrails service | Guardrail degradation is documented attack vector |
| Azure | Prompt Shields + Spotlighting | Entra ID CVSS 10.0 undermines all controls |
| Semantic Kernel | Input encoding by default | CVE-2026-26030 RCE via vector store |
| OpenAI | RL adversarial red-teaming | Admits "may never be fully solved" |
| **Stronghold** | **Gate + Warden 5-layer (regex/heuristic/semantic/LLM) + Sentinel post-call** | **None known** |

#### Multi-Tenant Data Isolation
| Platform | Isolation Model | Known Leakage |
|----------|----------------|---------------|
| OpenClaw | None (single-tenant) | Multi-user session isolation failure documented |
| LangChain | Workspace-level (paid) | Not documented |
| AutoGen | Azure VNet (paid) | Not documented |
| CrewAI | AMP enterprise (paid) | Not documented |
| Bedrock | AWS account boundary | Log manipulation, knowledge base compromise |
| Azure | Confidential Computing | CVE-2025-55241: cross-tenant impersonation |
| **Stronghold** | **Org→Team→User on ALL data queries** | **None — strict org_id filtering at data layer** |

#### Skill/Tool Supply Chain
| Platform | Marketplace Security | Known Incidents |
|----------|---------------------|-----------------|
| OpenClaw | None | **335 malicious skills** distributed (keyloggers, Atomic Stealer) |
| LangChain | Community hub, no scanning | LangGrinch via serialization |
| Cursor | MCP auto-invocation | MCP server impersonation (CVE-2025-59944) |
| **Stronghold** | **Trust tiers + security scan + Unicode normalization + SSRF block + T0 immutability** | **None** |

#### Privilege & Execution Model
| Platform | Execution Privilege | Code Execution |
|----------|-------------------|----------------|
| OpenClaw | Root by default | Full OS access |
| Cursor | Developer permissions + auto-exec tasks.json | Shell commands |
| Claude Code | User-level shell access | Arbitrary commands (regex-gated, bypassed) |
| AutoGen | Docker sandbox (optional) | Python execution in sandbox |
| **Stronghold** | **Non-root K8s pods, skills are prompts not code** | **No code execution — Sentinel validates all tool args** |

#### PII & Data Leakage
| Platform | PII Protection | Known Leakage |
|----------|---------------|---------------|
| OpenClaw | Partial (AES-256, not default) | Session data leakage across users |
| LangChain | Gateway only (paid) | Not documented |
| Bedrock | Guardrails PII filter | DNS exfiltration "intended functionality" |
| Claude Code | None | API key exfiltration via ANTHROPIC_BASE_URL |
| **Stronghold** | **15-pattern PII filter (AWS/GitHub/GitLab/OpenSSH/JWT/IP/email/password/connection strings)** | **None** |

### What Stronghold Defends Against That Others Don't

| Attack Class | Who Got Hit | What Happened | Stronghold Defense |
|-------------|-------------|---------------|-------------------|
| **Root execution** | OpenClaw | CVE-2026-25253: one-click RCE, 42K+ exposed | Non-root containers, K8s pod security |
| **Marketplace poisoning** | OpenClaw | 335 malicious skills (keyloggers, stealers) | Trust tiers + security scan + Unicode normalization |
| **Prompt → RCE chain** | LangChain | LangGrinch (CVSS 9.3): injection → serialization → code exec | No code execution pathway. Skills are prompts, not code |
| **Cross-tenant impersonation** | Azure | CVE-2025-55241 (CVSS 10.0): Entra ID | Org isolation at data layer, not just identity layer |
| **Tool result injection** | All OSS frameworks | LLM context poisoned by external API responses | Sentinel post-call: Warden scan + PII filter on every result |
| **ReDoS via security patterns** | None (proactive) | Theoretical — crafted inputs hang regex | 10KB scan window, input size limits |
| **SSRF via skill endpoints** | Pydantic AI (CVE-2026-25580) | Untrusted URLs fetched server-side | Private/metadata URL blocklist |
| **Learning/memory poisoning** | No other platform has learnings | N/A | Learning text scanned before mutation, T0/T1 immutable |
| **Session hijacking** | OpenClaw | Multi-user session isolation failure | Org-namespaced session IDs |
| **JSON bomb via tool args** | Theoretical | LLM generates massive tool arguments | 100KB arg size limit |
| **Context window stuffing** | Theoretical | Giant skill body wastes tokens | 50KB skill body limit |
| **on_behalf_of forgery** | Azure (CVE-2025-55241) | Service account impersonates admin | Cross-org validation on on_behalf_of claim |
| **Base64 encoded injection** | Not caught by any regex-only platform | Injection hidden in base64 payload | Warden Layer 2: encoded payload detection |
| **Homoglyph bypass** | Not addressed by any platform | Cyrillic characters bypass Latin regex | NFKD Unicode normalization in security scanner |
| **Static key theft → super admin** | OpenClaw | Root access + API keys in env | hmac.compare_digest + JWKS rotation + empty org_id = no data access |

### Key Differentiators

1. **Zero-trust by design** — Every other platform trusts SOMETHING by default (agents trust each other, tools trust input, marketplace trusts community). Stronghold trusts nothing.

2. **Security is not a paid tier** — LangChain, CrewAI, and AutoGen all gate security behind enterprise pricing. Stronghold's security is the base architecture.

3. **No code execution pathway** — OpenClaw, Cursor, Claude Code, and AutoGen all allow agents to execute code. Stronghold skills are prompt templates, not executable code. Tool execution goes through Sentinel validation.

4. **Org isolation at the data layer** — Azure and AWS isolate at the infrastructure level (accounts/VNets). Stronghold isolates at the query level — every `SELECT` is org-scoped. Infrastructure-level bugs (like Azure's CVSS 10.0) can't leak data because the application layer enforces boundaries independently.

5. **Self-evolution with security guardrails** — JiuwenClaw pioneered self-evolving agents but has no security controls on the evolution. Stronghold's learning→mutation pipeline has: learning text scanning, T0/T1 immutability, trust tier progression, and operator approval gates.

---

## OWASP Compliance

### OWASP Top 10 for LLM Applications (2025)
| ID | Threat | Stronghold Mitigation |
|----|--------|----------------------|
| LLM01 | Prompt Injection | Gate + Warden 5-layer scan (regex + heuristic + semantic + LLM) + tool result scanning |
| LLM02 | Sensitive Information Disclosure | PII filter + org-scoped data access |
| LLM03 | Supply Chain (Skills) | Trust tiers + security scanning + SSRF blocklist |
| LLM04 | Data/Model Poisoning | Learning scan before mutation + T0/T1 immutability |
| LLM05 | Improper Output Handling | Sentinel post-call pipeline (Warden + PII + optimize) |
| LLM06 | Excessive Agency | RBAC + Sentinel pre-call + tool permissions per role |
| LLM07 | System Prompt Leakage | Warden pattern: system prompt extraction queries |
| LLM08 | Embedding Weaknesses | Org-scoped embedding cache + hybrid fallback |
| LLM09 | Misinformation | Request sufficiency analyzer (knows when to ask, not guess) |
| LLM10 | Unbounded Consumption | Size limits on args, skills, learnings + scan window caps |

---

## Known Limitations (Honest Assessment)

1. ~~**Sentinel not yet in all strategies**~~ — ReactStrategy + DirectStrategy have it. **ArtificerStrategy still lacks Sentinel, Warden, PII, and size checks** (audit H1, highest priority fix).
2. **PII filter is regex-based** — homoglyph bypasses possible (mitigated by NFKD normalization). Missing Azure, Google, Slack, Stripe patterns.
3. ~~**No rate limiting**~~ — **FIXED**: Per-user sliding window rate limiter with burst limits (v1.0). In-memory only (not distributed).
4. ~~**Outcome store unbounded**~~ — **FIXED**: FIFO cap at 10K entries (v1.0).
5. **Static key auth returns `__system__` org_id** — system identity uses sentinel value, not empty string. `__system__` is a superadmin bypass — single point of failure for the entire multi-tenant boundary.
6. **No content safety** — no toxicity/hate-speech filtering (not Warden's scope).
7. **Timing side channels** — learning query time correlates with match count.
8. **L2.5 detection gap** — 37.5% of novel social engineering attacks evade semantic detection. L3 (LLM classifier) covers the gap but requires an LLM call. Code syntax in first 200 chars bypasses L2.5 entirely.
9. **PostgreSQL not yet default** — InMemory stores are functional but data is lost on restart. PG implementations exist but require `database_url` configuration.
10. **PG persistence layers lack org_id on agents and prompts** — PgAgentRegistry and PgPromptManager have no org_id column or filtering. Cross-tenant read/write/delete possible. (Audit C1-C4, blocks multi-tenant deployment.)
11. **Warden scan window gap** — Content between byte 10240 and (len-2048) is not scanned. Middle-content injection evades all Warden layers. (Audit H2.)
12. **L3 fail-open** — LLM classifier returns "safe" (not "inconclusive") on any exception. (Audit H3.)
13. **Demo JWT signing key = API key** — Anyone who knows the API key can forge arbitrary JWTs. Production must use separate JWT_SECRET + RS256. (Audit H5.)
14. **Admin routes with cross-tenant gaps** — 15 routes (agent CRUD, learning approve/reject, user roles, strike management, MCP server ops) lack org_id scoping. See BACKLOG.md for complete list.
15. **CSP allows `unsafe-inline`** — Dashboard script-src includes `'unsafe-inline'`, which neuters CSP as an XSS defense. (Audit M.)

---

## Reporting Vulnerabilities

Report security issues to: security@stronghold.dev (placeholder)

We follow responsible disclosure. Critical issues receive 48-hour response.
