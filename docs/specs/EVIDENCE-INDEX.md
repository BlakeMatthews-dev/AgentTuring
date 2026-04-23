# Evidence Index

External sources that informed design decisions. Stories cite these by short-code.

## Sources

### LangChain / DeepAgents
- **[EV-LC-DEEP-01]** Harness = complete system around the LLM (prompts, tools, config). LangChain blog: "Better Harness — A Recipe for Harness Hill-Climbing with Evals."
- **[EV-LC-DEEP-02]** Six-phase eval loop: source/tag → split → baseline → diagnose → experiment → validate. Evals as training data with optimization/holdout splits.
- **[EV-LC-DEEP-03]** Behavioral tagging on evals enables category-level diagnosis (tool-selection, multi-step-reasoning, etc.).
- **[EV-LC-DEEP-04]** Holdout set prevents overfitting; human review flags instructions overfit to optimization set.
- **[EV-LC-DEEP-05]** `deepagents` library: `create_deep_agent()` returns LangGraph graph. Todos and sub-agent spawn are tools the model calls, not orchestrator plumbing.
- **[EV-LC-DEEP-06]** File-based context spillover: large tool outputs go to files, not context window.

### LangGraph
- **[EV-LG-01]** StateGraph + nodes + edges with conditional routing. Directed graph execution model.
- **[EV-LG-02]** Checkpointing for durable execution — resume from any point after crash.
- **[EV-LG-03]** Interrupts for human-in-the-loop at any node boundary.
- **[EV-LG-04]** Time travel / replay from any checkpoint for debugging.

### Pi (Mario Zechner / Earendil)
- **[EV-PI-01]** Session tree with branching — every conversation point is a forkable node.
- **[EV-PI-02]** Philosophy: "features other agents bake in, you can build yourself." Kernel vs platform tradeoff.
- **[EV-PI-03]** Skills as progressive disclosure — on-demand loading prevents context bloat.

### OpenHarness (HKUDS)
- **[EV-OH-01]** 43+ tools with Pydantic schemas, permission modes (default/auto/plan/custom).
- **[EV-OH-02]** MCP client integration for third-party tool ecosystem.
- **[EV-OH-03]** Pre/PostToolUse hooks as extensible plugin surface.
- **[EV-OH-04]** Lazy skill loading prevents context inflation.

### Hyperagents (Meta, arxiv 2603.19461)
- **[EV-HYPERAGENTS-01]** Self-referential systems: task agent + meta agent. Meta agent modifies both task agent and itself.
- **[EV-HYPERAGENTS-02]** DGM-Hyperagents: meta-level modification procedure is itself editable. Self-accelerating improvement.
- **[EV-HYPERAGENTS-03]** Generational evolution with genealogy tracking. Staged evaluation (small sample → full eval).
- **[EV-HYPERAGENTS-04]** Meta-level enhancements (memory systems, performance tracking) transfer across domains and accumulate across runs.

### DSPy (Stanford)
- **[EV-DSPY-01]** Prompt-program compilation: automates prompt optimization from examples + metrics.
- **[EV-DSPY-02]** Signatures as typed input→output contracts for prompts.
- **[EV-DSPY-03]** Optimizers (BootstrapFewShot, MIPRO) search prompt space systematically.

### Letta / MemGPT
- **[EV-LETTA-01]** Self-editing memory tool calls: agents explicitly write/update their own memories.
- **[EV-LETTA-02]** Working vs archival memory paging for long-running sessions.

### Zep / Graphiti
- **[EV-ZEP-01]** Temporal knowledge graph for agent memory with timestamped fact extraction.

### Inspect AI (UK AISI)
- **[EV-INSPECT-01]** Solver/scorer/dataset abstraction for rigorous eval framework.
- **[EV-INSPECT-02]** Sandbox per eval sample for isolation.

### SWE-bench
- **[EV-SWEBENCH-01]** Standard benchmark for coding agent evaluation. Real GitHub issues as test cases.

### OpenHands / SWE-agent
- **[EV-OPENHANDS-01]** Event-stream architecture with pluggable runtimes (Docker/local/remote).
- **[EV-SWEAGENT-01]** Agent-Computer Interface — constrained action space for coding tasks.

### FrugalGPT / Model Cascades
- **[EV-FRUGAL-01]** Cheap-first model cascading: escalate to expensive model only on low confidence.

### Anthropic / Claude
- **[EV-ANTHROPIC-01]** Prompt caching / KV reuse — cache breakpoints in system prompts reduce cost.
- **[EV-ANTHROPIC-02]** Apply-model separation: cheap fast model applies edits the strong model proposed.
