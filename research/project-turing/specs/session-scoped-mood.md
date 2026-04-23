# Spec 58 — Session-scoped mood

*Per-conversation sub-mood that inherits from and decays toward the global mood. "How I feel about this conversation right now" as distinct from "my overall mood today."*

**Depends on:** [mood.md](./mood.md), [conversation-threads.md](./conversation-threads.md), [self-schedules.md](./self-schedules.md), [memory-mirroring.md](./memory-mirroring.md), [mood-rolling-sum-guard.md](./mood-rolling-sum-guard.md).
**Depended on by:** [mood-affects-decisions.md](./mood-affects-decisions.md).

---

## Current state

Spec 27 mood is singleton per `self_id`. Spec 54 introduces per-user conversation threads. A single global mood can't represent "I'm generally fine today but this particular conversation is tense" — a natural state that both humans and autonoetic selves have.

## Target

A `conversation_mood` table layered on top of `self_mood`:
1. At conversation creation, session mood is **initialized as a copy of the current global mood**.
2. On each message in the conversation, session mood decays **toward the current global mood** (not toward neutral directly) at a faster rate.
3. Event nudges default to the active conversation's mood. `apply_event_nudge(..., scope="global")` is the opt-out.
4. Prompt rendering uses session mood when a conversation is active, global otherwise.
5. Archived conversations freeze their session mood row for audit; it no longer ticks.

## Acceptance criteria

### Schema

- **AC-58.1.** New table `conversation_mood`:
  ```sql
  CREATE TABLE conversation_mood (
      conversation_id     TEXT PRIMARY KEY REFERENCES conversations(id),
      self_id             TEXT NOT NULL REFERENCES self_identity(self_id),
      valence             REAL NOT NULL CHECK (valence BETWEEN -1.0 AND 1.0),
      arousal             REAL NOT NULL CHECK (arousal BETWEEN 0.0 AND 1.0),
      focus               REAL NOT NULL CHECK (focus BETWEEN 0.0 AND 1.0),
      last_tick_at        TEXT NOT NULL,
      inherited_from_global_at TEXT NOT NULL,
      updated_at          TEXT NOT NULL
  );
  ```
  Test.
- **AC-58.2.** One row per live conversation. Creating a row for an already-existing conversation raises (PK collision). Test.

### Inheritance at conversation creation

- **AC-58.3.** `ConversationRepo.create(...)` (spec 54) additionally inserts a `conversation_mood` row whose dimensions are copied from the current `self_mood` for this `self_id`. `inherited_from_global_at = now()`. Test.
- **AC-58.4.** If `self_mood` does not exist yet (pre-bootstrap completion — shouldn't happen in production), the session row is not created and subsequent lookups fall back to neutral. Test.

### Decay-toward-global

- **AC-58.5.** `tick_session_mood(conversation_id, now)` applies compound decay **toward the global mood** per dimension:
  ```
  new_dim = current_session + SESSION_DECAY_RATE_EFFECTIVE(hours) × (global_dim - current_session)
  ```
  With `SESSION_DECAY_RATE = 0.3 per hour` (three times faster than global's 0.1/hour). Test.
- **AC-58.6.** Session ticks fire on every message receipt within that conversation (spec 54's append-message path) AND on an hourly scheduled sweep over all active conversations. Test both.
- **AC-58.7.** Decay never crosses the global target in the same direction (asymptotic; analogous to spec 27 AC-27.7). If global mood moves during the tick, the session chases the new target. Test.

### Event nudges

- **AC-58.8.** `apply_event_nudge(self_id, event, reason, *, scope="session" | "global" | "both")` — default `scope` is `"session"` when called from within a `conversation_scope(conversation_id)`; otherwise `"global"`. Test defaults.
- **AC-58.9.** `scope="both"` applies the nudge to both global and session mood. Useful for events that clearly affect overall state (e.g., `warden_alert_on_ingress`). Test.
- **AC-58.10.** A conversation-scoped event that would move session valence below its `MOOD_ROLLING_SUM_CAP` (per-conversation, spec 42) is clipped as in spec 42. Per-conversation rolling-sum budget runs independently of the global budget. Test.

### Conversation-scope context

- **AC-58.11.** `conversation_scope(conversation_id)` is a `contextvars.ContextVar` set at the start of every request that resolves to a conversation, released at end. Rendering and nudging read this var. Test.
- **AC-58.12.** Multiple requests within the same conversation share the session mood; nudges accumulate across messages within the conversation. Test.

### Prompt rendering

- **AC-58.13.** `render_minimal_block(self_id)` (spec 28) reads `conversation_scope`; if set AND `conversation_mood` exists for it, the mood descriptor line uses session mood. Otherwise global. Test.
- **AC-58.14.** The descriptor line gains a subtle hint when session ≠ global: `"Right now, in this conversation: {session_descriptor} (in general today: {global_descriptor})."` Only when the two descriptors differ AND the Euclidean distance between session and global mood vectors exceeds `DESCRIPTOR_DIVERGENCE_THRESHOLD = 0.3`. Otherwise single-line format. Test.
- **AC-58.15.** `recall_self()` returns `mood.global` and `mood.session` (when in a conversation). Test.

### Archival

- **AC-58.16.** When a conversation is archived (spec 54 AC-54.14), its `conversation_mood` row remains but no longer ticks. Last-tick-time frozen at archive time. Test.
- **AC-58.17.** A read on an archived session mood returns the frozen state. Test.
- **AC-58.18.** Auto-archived conversations (spec 54 AC-54.17) likewise freeze their session mood. Test.

### Memory mirroring

- **AC-58.19.** Every session-mood nudge writes an OBSERVATION via memory mirror with `intent_at_time = "mood nudge (session)"`, `context = {conversation_id, dim, delta, reason, scope}`. Distinguishable from global nudges by the `scope` field. Test.
- **AC-58.20.** Every session-mood tick does NOT write an OBSERVATION (would be too noisy at message frequency). Test no tick memories created.

### Cross-conversation bleed

- **AC-58.21.** Session mood of conversation A does NOT affect conversation B. Two concurrent conversations with opposite mood trajectories end up in different session states. Test.
- **AC-58.22.** Global mood reflects the **running mean** of session moods' influence: when a session nudge fires with `scope="session"`, the global is untouched. A `scope="both"` nudge moves both. A system-level nudge (warden_alert on a non-conversation request) moves global only. Test.

### Activation graph interaction

- **AC-58.23.** `source_kind == "mood"` in the activation graph reads **global** mood unless a `conversation_scope` is active, in which case it reads session. Test.

### Budget interaction

- **AC-58.24.** Spec 42's mood rolling-sum guard is computed per-scope: each conversation has its own 7-day budget, global has its own. A conversation with capped mood does not prevent another conversation from nudging. Test.

### Edge cases

- **AC-58.25.** A conversation that re-opens after weeks of inactivity: on first message, `tick_session_mood` fires with `hours = (now - last_tick_at) / 3600`, which rapidly pulls the stale session toward the current global. Asymptotic — correct. Test.
- **AC-58.26.** `scope="session"` nudge outside a conversation (e.g., from a scheduled background task) raises `NoActiveConversation` rather than falling back to global. Test.
- **AC-58.27.** Concurrent nudges on the same conversation serialize via an advisory lock `mood-session:{conversation_id}`. Test.
- **AC-58.28.** Dropping a conversation's last message and re-creating it (spec 54 permits) preserves the session mood row; it does not reinitialize. Test.

## Implementation

```python
# self_mood.py additions

SESSION_DECAY_RATE: float = 0.3          # per hour
DESCRIPTOR_DIVERGENCE_THRESHOLD: float = 0.3


_conversation_scope_var: ContextVar[str | None] = ContextVar(
    "conversation_scope", default=None,
)


@contextmanager
def conversation_scope(conversation_id: str) -> Iterator[None]:
    token = _conversation_scope_var.set(conversation_id)
    try:
        yield
    finally:
        _conversation_scope_var.reset(token)


def tick_session_mood(repo, conversation_id: str, now: datetime) -> SessionMood:
    with repo.advisory_lock(f"mood-session:{conversation_id}"):
        session = repo.get_conversation_mood(conversation_id)
        if session is None:
            return None  # archived or never initialized
        global_mood = repo.get_mood(session.self_id)
        hours = max(0.0, (now - session.last_tick_at).total_seconds() / 3600.0)
        if hours <= 0:
            return session
        effective = 1.0 - (1.0 - SESSION_DECAY_RATE) ** hours
        session.valence += effective * (global_mood.valence - session.valence)
        session.arousal += effective * (global_mood.arousal - session.arousal)
        session.focus   += effective * (global_mood.focus   - session.focus)
        session.last_tick_at = now
        repo.update_conversation_mood(session)
        return session


def apply_event_nudge(
    repo, self_id: str, event: str, reason: str,
    *, scope: str | None = None,
) -> None:
    effective_scope = scope or _default_scope_for_context()
    for dim, delta in EVENT_NUDGES.get(event, []):
        if effective_scope in ("session", "both"):
            conv_id = _conversation_scope_var.get(default=None)
            if conv_id is None:
                raise NoActiveConversation(event)
            nudge_session_mood(repo, conv_id, dim, delta, reason=f"{event}: {reason}")
        if effective_scope in ("global", "both"):
            nudge_mood(repo, self_id, dim, delta, reason=f"{event}: {reason}")
```

Schema migration adds `conversation_mood` table and indices.

## Open questions

- **Q58.1.** Session decay rate is 3× global (0.3 vs 0.1 per hour). Rationale: session is "this specific encounter" — rebounds faster. Tune empirically.
- **Q58.2.** `scope="both"` for `warden_alert_on_ingress` feels right; an attempted attack colors both this conversation and my general wariness. Make this the default for a named subset of events via a `DEFAULT_SCOPE_BY_EVENT` map, rather than hardcoded case-by-case.
- **Q58.3.** The divergence hint "in general today: X" in the minimal block leaks information about other conversations to the current user. A determined user can infer recent unrelated events. Acceptable for research single-user; flag for any multi-user deployment.
- **Q58.4.** Session mood on a conversation that happens to be a "first-contact" interactive-bootstrap session (spec 56): session inherits from neutral global (since bootstrap is fresh). No special case needed.
- **Q58.5.** If spec 42's rolling-sum budget is per-conversation, a user with many concurrent conversations could cumulatively nudge the global (via `scope="both"` events). The global rolling-sum still bounds total drift, so OK; worth watching.
