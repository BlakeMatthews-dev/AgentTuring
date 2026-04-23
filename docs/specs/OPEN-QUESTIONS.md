# Open Questions

Unresolved design decisions. Each question is keyed by epic. Resolve before or
during implementation of the associated epic.

## Epic 01: Eval Substrate
- **OQ-EVAL-01**: Phoenix behavioral-tagging schema owner — platform team defines
  tags, or per-tenant custom tags allowed?
- **OQ-EVAL-02**: SWE-bench dataset subset — full 2294 instances or a curated
  subset relevant to Stronghold's coding patterns?
- **OQ-EVAL-03**: Eval artifact storage — local filesystem, PostgreSQL, or S3?

## Epic 02: CapabilityProfile
- **OQ-CAP-01**: Skill-score decay function — linear, exponential, or none when
  a capability goes unused?
- **OQ-CAP-02**: Cost-vector aggregation across nested agent calls — sum, max, or
  separate per-hop channels?
- **OQ-CAP-03**: Cold-start exploration policy — Thompson sampling,
  epsilon-greedy, or fixed exploration budget for new agents?

## Epic 03: Agent-Call ACLs
- **OQ-ACL-01**: Originating-principal propagation across async boundaries (task
  queue, A2A peer calls) — does the principal survive serialization?
- **OQ-ACL-02**: Default depth limit — 3? 5? Configurable per-agent?

## Epic 04: Taxonomy
- **OQ-TAX-01**: Does substrate include deterministic HTTP clients (e.g.,
  geocoding, currency conversion), or are all HTTP calls tool calls requiring
  a heavy agent?
- **OQ-TAX-02**: Can a light agent be promoted to heavy at runtime, or is kind
  immutable after registration?

## Epic 06: Conduit Reasoning Agent
- **OQ-CONDUIT-01**: Fallback behavior when reasoning loop diverges or exceeds
  cost budget — hard abort, or degrade to heuristic router?
- **OQ-CONDUIT-02**: Maximum reasoning turns for Conduit before forced response?

## Epic 07: DSPy
- **OQ-DSPY-01**: Runtime DSPy compilation vs ahead-of-time — where is the
  compiled cache stored?
- **OQ-DSPY-02**: Which DSPy optimizer to start with — BootstrapFewShot (simple)
  or MIPRO (stronger but slower)?

## Epic 08: Prompt Versioning
- **OQ-PROMPT-01**: Rollback granularity — per-agent, per-signature, or per-
  version tag?
- **OQ-PROMPT-02**: How many versions retained before GC?

## Epic 09: Canary + Tournament
- **OQ-CANARY-01**: Naming collision between existing `skills/canary.py` and
  proposed `agents/canary.py` — rename one?
- **OQ-CANARY-02**: Traffic percentage for canary cohort — fixed 5%, or
  configurable per-epic?

## Epic 10: Mid-Session Model Switching
- **OQ-SWITCH-01**: Who owns the continuity contract when the model changes
  mid-tool-call — the calling agent or the Conduit?

## Epic 11: Group Chat Patterns
- **OQ-DEBATE-01**: Scribe debate convergence criterion — fixed rounds, quality
  threshold, or judge-agent decision?
- **OQ-DEBATE-02**: Maximum debate participants before diminishing returns?

## Epic 12: Memory v2
- **OQ-MEM-01**: Temporal knowledge graph storage backend — pgvector-adjacent
  extension, or external graph DB (Neo4j)?
- **OQ-MEM-02**: Self-editing memory scope — can an agent edit another agent's
  memories, or only its own?

## Epic 13: Hyperagents Meta-Level
- **OQ-META-01**: Safety circuit breaker threshold — what rate of self-mutation
  triggers a freeze? Per-hour? Per-day?
- **OQ-META-02**: Meta-improvement rollback — does rolling back a meta-change
  also roll back the task-level changes it produced?

## Epic 14: Artificer v2
- **OQ-ART-01**: Gatekeeper vs Warden role boundary — is Gatekeeper a new agent
  or a Warden mode?
- **OQ-ART-02**: When is "enough learning" from the current loop to trigger v2
  design freeze — number of battles, Elo threshold, or calendar gate?
