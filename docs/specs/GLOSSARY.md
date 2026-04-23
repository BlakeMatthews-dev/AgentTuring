# Glossary

Terms used across all epic specs. Canonical definitions only — no design
rationale (that lives in epic READMEs and ARCHITECTURE.md).

## Agent Classification

**Heavy Agent** — an agent with its own container, tools, and real side effects.
Every side effect in the system originates from a heavy agent. Examples: Mason,
Archie, Auditor, Ranger, Warden-at-Arms, Forge.

**Light Agent** — an agent with NO tools. It has access to the substrate and
permission to call other agents. All side effects are delegated to heavy agents.
Examples: imported specialists, Forge-created agents, orchestration compositions.

**Substrate** — capabilities available to all agents without permission gating.
LLM inference, tracing, context assembly, and deterministic pure utilities (time,
UUID, hashing, parsing). Not a tool — the fabric agents exist within.

## Capability Dimensions

**Permission** — binary (allowed/blocked). Sentinel enforces. Governs whether an
agent *can* perform an action. Includes both tool permissions and agent-call
permissions.

**Skill Score** — continuous (0–10). Outcome-derived, per (agent, capability,
intent_class). Governs whether an agent *should* perform an action itself or
delegate. Updated by pseudoRLHF/DSPy from eval outcomes.

**Cost Vector** — composite: `{standing, cold_start_ms, per_call_compute,
per_call_tokens, tool_fees, overhead}`. Measured, not declared. Includes
container resource cost (CPU/memory/GPU reservation). Used by reasoning agents
to make economic delegation decisions.

**CapabilityProfile** — the full `(agent, capability, intent_class) → (permission,
skill, cost)` record. The data structure reasoning agents consume when deciding
whether to self-execute, delegate, or decline.

## Security Primitives

**Originating Principal** — the root caller identity propagated through the
entire call chain. Used for transitive escalation checks: if Scribe initiated the
chain, Mason refuses code_gen even if called via an intermediate agent.

**Call Chain** — `list[AgentId]` appended on every sub-agent invocation. Checked
for cycles, depth limits, and originating-principal denial.

**Trust Tier** — Skull (unusable) → T3 (sandboxed) → T2 (community) → T1
(operator-vetted) → T0 (built-in). Orthogonal to CapabilityProfile — trust is
about provenance, capability is about competence.

## Improvement Loop

**pseudoRLHF** — the existing inner improvement loop: Auditor reviews →
Extractor finds fail→succeed patterns → Promoter auto-promotes on hit threshold
→ SkillForge bakes promoted learnings into prompts.

**Meta-Level Improvement** — Hyperagents-inspired outer loop: DSPy optimizes the
pseudoRLHF components themselves (Auditor rubric, Extractor patterns, Promoter
thresholds). The improvement process improves itself.

**Behavioral Tag** — a categorical label on a Phoenix trace span classifying the
failure mode (e.g., tool-selection, multi-step-reasoning, delegation-error).
Used for category-level diagnosis and eval-set slicing.

**Optimization Set** — eval examples used to drive DSPy compilation / prompt
optimization. Improvements measured here.

**Holdout Set** — eval examples reserved for generalization validation. Never
used during optimization. Prevents overfitting.

## Deployment

**Canary** — staged promotion: new prompt/agent version serves a small cohort
before full rollout. Auto-rollback on regression against holdout.

**Shadow Mode** — parallel-run a candidate alongside the incumbent. Both execute;
only incumbent's result serves the user. Candidate builds an eval track record.

**Feature Flag** — every epic ships behind `STRONGHOLD_<EPIC>_ENABLED`. Default
off. Operator activates when ready.
