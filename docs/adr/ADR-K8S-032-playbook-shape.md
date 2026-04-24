# ADR-K8S-032 — Agent-oriented Playbook shape

**Status:** Accepted
**Date:** 2026-04-23
**Deciders:** Stronghold core team

## Context

MCP servers today are designed for human programmers (REST-shaped, fine-
grained, many small tools, raw JSON) but their actual consumers are
reasoning LLMs. Reasoning LLMs perform better with fewer, more powerful
tools with task-oriented names, pre-filtered outputs shaped as markdown,
natural-language inputs, defaults, dry-run on writes, and "you probably
want X next" hints.

Stronghold's pre-redesign tool surface was a monolithic
`github(action=…)` with 14 action handlers plus several thin tools. The
agent would chain 5-6 low-level calls to review a PR, each returning
large JSON blobs. Token economy was poor, tool-selection accuracy
degraded past ~14 actions, and the JSON shape forced the LLM to
assemble its own narrative from metadata.

## Decision

**Ship a Playbook abstraction as a peer to the thin-tool surface.**

- A **Playbook** is an async function `(inputs: dict, ctx: PlaybookContext)
  -> Brief` registered via `@playbook(name, …)`.
- Every Playbook returns a **Brief**: a dataclass (title, summary,
  sections, flags, next_actions, source_calls) that renders to markdown
  sized for the 6 KB default budget (12 KB if `allow_large=True`).
- Playbooks compose multiple backend API calls **server-side** (e.g.
  `review_pull_request` fans out 6 concurrent GitHub REST calls) and
  surface a single reasoning-ready brief.
- The primary MCP surface is capped at **≤20 playbooks** plus one
  `*_raw` escape hatch per integration for the 1% of cases no playbook
  covers.
- **Write playbooks** support `dry_run`, auto-injected into the schema
  by the `@playbook(writes=True)` decorator, so a caller can preview
  the planned action before committing.

Transport: the MCP wire server (ADR-K8S-020 / ADR-K8S-024) exposes
playbooks over stdio + Streamable HTTP. The agent loop at
`agents/strategies/react.py:165` calls playbooks through the same
`tool_executor` callback used for thin tools via the
`PlaybookToolExecutor` adapter — no wire change, no protocol change.

## Rationale

- **Token economy.** Measured 88% byte reduction on the PR-review task
  when switching from 6 raw GitHub endpoints to the
  `review_pull_request` playbook (29059 B → 3492 B) on realistic
  GitHub API-shaped fixtures. See
  `tests/integration/playbooks/test_token_economy.py`.
- **Tool-selection accuracy.** Fewer, clearer tools → fewer wrong
  picks. Target surface ≤20 keeps us well below the ~40-50 threshold
  where model tool-selection degrades.
- **Alignment with design principles** (CLAUDE.md): #1 cheapest
  reliable tool (server-side composition over model orchestration),
  #2 runtime in charge, #6 budget context windows, #7 bounded autonomy.
- **Sentinel simplification.** Pre/post-call in-process wrap was
  already the real code path; the LiteLLM-guardrail framing in
  earlier drafts never matched reality. Accepting this ADR lets us
  correct ARCHITECTURE.md §3.3.

## Consequences

- Each playbook is its own mini-app (~200-300 LOC composition + 60-80
  LOC Brief rendering). More server code than a thin-tool wrapper, but
  the token economy pays for it many times over.
- Existing `github(action=…)` callers go through a deprecation shim
  (`src/stronghold/tools/github_shim.py`) while they migrate; the
  shim emits `DeprecationWarning` per call and will be retired in a
  follow-up sprint.
- Markdown briefs are harder to chain programmatically than JSON. An
  optional `structured_appendix: dict` may be added later if a
  legitimate programmatic consumer emerges, but the default shape
  remains markdown for reasoning consumption.

## References

- ARCHITECTURE.md §5.1 (rewritten 2026-04-23)
- ARCHITECTURE.md §5.2 (new — Playbook + Brief contract)
- ADR-K8S-020, ADR-K8S-024 (server + transport architecture)
- `/root/.claude/plans/well-zesty-avalanche.md` (implementation plan)
