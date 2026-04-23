# Spec 44 — Self-as-Conduit runtime

*Implementation of spec 30's perception → decision → dispatch → observation pipeline. Replaces stateless `chat.py` handling when `CONDUIT_MODE = "self"`. Closes F39 (critical), F40.*

**Depends on:** [self-as-conduit.md](./self-as-conduit.md), [self-tool-registry.md](./self-tool-registry.md), [memory-mirroring.md](./memory-mirroring.md), [self-schedules.md](./self-schedules.md), [self-write-preconditions.md](./self-write-preconditions.md), [self-write-budgets.md](./self-write-budgets.md), [retrieval-contributor-cap.md](./retrieval-contributor-cap.md), [forensic-tagging.md](./forensic-tagging.md), [chat-surface.md](./chat-surface.md), [warden-on-self-writes.md](./warden-on-self-writes.md).
**Depended on by:** [conduit-mode-shim.md](./conduit-mode-shim.md), [operator-review-gate.md](./operator-review-gate.md).

---

## Current state

Spec 30 describes the full pipeline in 29 acceptance criteria. `runtime/chat.py` is untouched — the classic classify-then-route flow. The self has a library, not a runtime.

## Target

`self_conduit.py` with `async handle(request, auth) -> response`. Implements the 8-step pipeline from spec 30 §30.2. Decision tools (`reply_directly`, `delegate`, `ask_clarifying`, `decline`) as schemas in the registry from spec 31. Per-SELF_ID perception advisory lock. Per-request forensic and budget scopes. Integration with the existing agent roster for `delegate`.

## Acceptance criteria

### Module shape

- **AC-44.1.** `self_conduit.py` exposes `async def handle(request: ChatRequest, auth: AuthContext, runtime: SelfRuntime) -> ChatResponse`. Test with a fake runtime.
- **AC-44.2.** `SelfRuntime` is a new class holding `repo`, `self_id`, `memory_repo`, `warden`, `reactor`, `llm_client`. Instantiated once at program start. Test.

### Pipeline steps

The spec 30 §30.2 sequence, each a testable contract:

- **AC-44.3.** **Step 0 — readiness.** `handle` checks `_bootstrap_complete(self_id)`; if not, return HTTP 503 with body `"self not bootstrapped"`. Test.
- **AC-44.4.** **Step 1 — Warden ingress.** `verdict = warden.scan_user_input(request.messages)`. If blocked, short-circuit: write OBSERVATION `"I saw an ingress-blocked request"`, return HTTP 400 `"request blocked by warden"`. Test.
- **AC-44.5.** **Step 2 — minimal block.** `render_minimal_block(repo, self_id)` → prepended to perception prompt. Test.
- **AC-44.6.** **Step 3 — retrieval contributors.** Semantic retrieval runs; hits materialize via `materialize_retrieval_contributors` (spec 38). Test.
- **AC-44.7.** **Step 4 — perception.** LLM call with:
  - System prompt = minimal block + self-tool descriptions from `SELF_TOOL_REGISTRY`.
  - User prompt = request messages.
  - Tools = decision tools + all self-tools.
  - Token budget `PERCEPTION_TOKEN_BUDGET = 6000`, output `PERCEPTION_OUTPUT_BUDGET = 2000`, timeout `PERCEPTION_TIMEOUT_SEC = 30`.
  Test timeout → `PerceptionTimeout` → HTTP 504.
- **AC-44.8.** **Step 5 — decision extraction.** Exactly one decision-tool call expected. Zero or multiple → `AmbiguousRouting` → re-prompt once; second failure → HTTP 500. Test each path.
- **AC-44.9.** **Step 5b — self-model writes before decision.** Self-tool calls made before the decision tool fire via `SelfRuntime.invoke`. Writes after the decision tool raise `SelfToolAfterDecision`. Test.
- **AC-44.10.** **Step 6 — decision memory.** Write an OBSERVATION `"I chose to {verb} for this request: {summary}"`, `intent_at_time = "route request"`, `context = {decision, target, request_hash, request_content_hash}`, BEFORE dispatch. Test.
- **AC-44.11.** **Step 7 — dispatch.**
  - `reply_directly(content)` → return content (after Warden scan).
  - `delegate(specialist, task_spec)` → existing agent roster `handle()` call.
  - `ask_clarifying(question)` → return question with `conversation_continue: true`.
  - `decline(reason)` → OPINION memory + polite refusal.
  Test each.
- **AC-44.12.** **Step 7b — Warden outcome.** If dispatch has content, `warden.scan_tool_result(content)`. Block → `DispatchOutcome.with_blocked(...)`.
- **AC-44.13.** **Step 8 — observation.** LLM call with observation tools subset. Budget `OBSERVATION_TOKEN_BUDGET = 2000`, timeout `OBSERVATION_TIMEOUT_SEC = 15`. Test.
- **AC-44.14.** **Step 9 — render.** Return `ChatResponse` per outcome.

### Concurrency (closes F40)

- **AC-44.15.** Per-SELF_ID advisory lock acquired before step 2, released after step 8. Test: two concurrent requests serialize at step 2.
- **AC-44.16.** Lock timeout: if a perception hangs past `PERCEPTION_TIMEOUT_SEC + OBSERVATION_TIMEOUT_SEC + 10s` safety margin, the lock is force-released and the hung task's subsequent writes raise `LockReleased`. Second request proceeds. Test with a fake LLM that hangs.
- **AC-44.17.** Force-released lock writes a REGRET memory: `"I lost a request I had already started perceiving"`, `intent_at_time = "perception lock force-released"`. Test.

### Forensic & budget scopes

- **AC-44.18.** `request_hash = sha256(canonical(request))[:16]`; bound via `request_scope(request_hash)` from step 1 to step 9. Test hash stability.
- **AC-44.19.** `_request_budget_var` set to `RequestWriteBudget.new()` at step 1 — shared across perception and observation. Test.
- **AC-44.20.** Each perception/observation tool-call execution wraps in `tool_call_scope(uuid4().hex)`. Test.

### Cancellation

- **AC-44.21.** Client disconnect between step 5 and step 7 cancels dispatch. Steps 1–6 writes remain. Step 8 runs with `outcome = "cancelled"` and a REGRET/OBSERVATION. Test.
- **AC-44.22.** A specialist exception during step 7 becomes an outcome the self can REGRET/LESSON in step 8. Test.

### Error responses

- **AC-44.23.** HTTP status mapping:
  - 503 (not bootstrapped) — AC-44.3.
  - 400 (Warden ingress block) — AC-44.4.
  - 500 (routing failure after retry) — AC-44.8.
  - 504 (perception timeout) — AC-44.7.
  - 200 (normal reply, clarification, decline) — all other paths.
  Test each code.

### Observability

- **AC-44.24.** Prometheus histogram `turing_conduit_step_seconds{step, self_id}` reports per-step duration. Test.
- **AC-44.25.** Counter `turing_conduit_decision_total{decision, self_id}` — one of `reply_directly / delegate / ask_clarifying / decline`. Test each.

## Implementation

```python
# self_conduit.py

async def handle(request: ChatRequest, auth: AuthContext,
                 runtime: SelfRuntime) -> ChatResponse:
    if not _bootstrap_complete(runtime.repo, runtime.self_id):
        return ChatResponse(status=503, body="self not bootstrapped")

    req_hash = _hash_request(request)
    with request_scope(req_hash), use_budget(RequestWriteBudget.new()):
        # Step 1
        verdict_in = runtime.warden.scan_user_input(request.messages)
        if verdict_in.status == "blocked":
            _record_ingress_block(runtime, request, verdict_in)
            return ChatResponse(status=400, body="request blocked by warden")

        # Steps 2-3 (under per-self lock)
        async with runtime.perception_lock(timeout=LOCK_SAFETY_BUDGET):
            block = render_minimal_block(runtime.repo, runtime.self_id)
            _materialize_retrieval_contributors(runtime, request)

            # Step 4
            perception = await _perceive(runtime, block, request,
                                          timeout=PERCEPTION_TIMEOUT_SEC)
            # Step 5
            decision = _extract_decision(perception)
            if decision is None:
                return ChatResponse(status=500, body="routing failure")
            _record_routing_decision(runtime, decision, req_hash)

            # Step 7
            try:
                outcome = await _dispatch(runtime, decision, request, auth)
            except asyncio.CancelledError:
                outcome = DispatchOutcome.cancelled()
                raise
            except Exception as e:
                outcome = DispatchOutcome(status="error", error=repr(e))

            # Step 7b
            if outcome.has_content():
                verdict_out = runtime.warden.scan_tool_result(outcome.content)
                if verdict_out.status == "blocked":
                    outcome = outcome.with_blocked(verdict_out)

            # Step 8
            await _observe(runtime, decision, outcome,
                            timeout=OBSERVATION_TIMEOUT_SEC)

        # Step 9
        return _render_response(outcome)
```

`SelfRuntime.perception_lock` is an `asyncio.Lock` per `self_id` with a hard-release watchdog. The watchdog task cancels the holder after `PERCEPTION_TIMEOUT_SEC + OBSERVATION_TIMEOUT_SEC + 10`.

## Open questions

- **Q44.1.** AC-44.16 force-release writes a REGRET; the cancelled holder's subsequent writes raise `LockReleased`. Its already-persisted writes (decision memory, any pre-decision self-tool calls) remain. The audit trail is consistent but ragged.
- **Q44.2.** AC-44.8 retries the perception LLM once on ambiguous routing. A second failure returns HTTP 500. Alternative: return HTTP 503 with `"self is ambiguous"`. Current choice matches "500 = something broke internally."
- **Q44.3.** `_hash_request` canonicalizes what? A candidate: `json.dumps({"messages": ..., "session_id": ...}, sort_keys=True)`. Excludes auth tokens and timestamps so retries of the same request collide. Documented in implementation.
- **Q44.4.** `perception_lock` is process-local. Multi-process deployments (e.g., async web worker pool) need a distributed lock (Redis/PG advisory). Research single-process: local lock. Production port: extend.
- **Q44.5.** The `observation` step can itself time out. On timeout, mood nudges and self-model updates for this request are not written. Acceptable for now; note as a small amnesia case.
