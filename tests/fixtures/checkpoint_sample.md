---
checkpoint_id: 20260422-143015-canary-layer-wiring
session_id: abc-123-def-456
source: claude_code
branch: warden/canary-layer
summary: Canary token scanner wired into Warden; tests passing through detector chain.
decisions:
  - Per-session lifetime, rotate on detection.
  - Store in dedicated CanaryStore rather than reusing SessionStore.
remaining:
  - Add perf test under 2ms latency target.
  - Update ARCHITECTURE.md §3.1.
notes:
  - Heuristics layer test suite unchanged — canary sits before it.
failed_approaches:
  - Initially tried context-var plumbing; switched to explicit arg for clarity.
created_at: 2026-04-22T14:30:15+00:00
scope: session
agent_id: artificer
user_id: engineer-1
org_id: acme
team_id: platform
---

# Canary layer wiring

Free-form body if the skill captured more context than fits in frontmatter.
