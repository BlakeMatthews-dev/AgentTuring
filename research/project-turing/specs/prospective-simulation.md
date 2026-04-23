# Spec 60 — Prospective simulation

*Before routing, the self imagines the outcome of each candidate specialist and compares with actuals. "What do I expect if I route to X?" — first-person forward retrieval, surprise-delta feedback.*

**Depends on:** [conduit-runtime.md](./conduit-runtime.md), [semantic-retrieval.md](./semantic-retrieval.md), [memory-mirroring.md](./memory-mirroring.md), [activation-graph.md](./activation-graph.md), [schema.md](./schema.md).
**Depended on by:** [prospection-accuracy-detector.md](./prospection-accuracy-detector.md).

---

## Current state

DESIGN.md §5 promises "participant simulation by the pipeline itself, using the same machinery as episodic recall." Spec 30 mentions it in passing (§30.2 observation stage). No spec defines the mechanism or schema.

## Target

A prospection step inserted at spec 44 step 5 (after decision extraction, before dispatch). For each *candidate* specialist the perception LLM is considering (the top-2 from its internal reasoning, plus the ultimate chosen one), retrieve similar past routings and generate an expected-outcome summary. Persist the predictions. After dispatch, compute surprise-delta between predicted and actual; mint a memory carrying the delta.

## Acceptance criteria

### Schema

- **AC-60.1.** New table:
  ```sql
  CREATE TABLE prospective_predictions (
      id                 TEXT PRIMARY KEY,
      self_id            TEXT NOT NULL REFERENCES self_identity(self_id),
      request_hash       TEXT NOT NULL,
      candidate_specialist TEXT NOT NULL,
      predicted_outcome_summary TEXT NOT NULL,
      predicted_confidence REAL NOT NULL CHECK (predicted_confidence BETWEEN 0.0 AND 1.0),
      actual_outcome_summary TEXT,          -- filled post-dispatch
      surprise_delta     REAL,              -- filled post-dispatch, [0.0, 1.0]
      chosen             INTEGER NOT NULL DEFAULT 0,  -- 1 if this was the dispatched specialist
      created_at         TEXT NOT NULL,
      resolved_at        TEXT
  );
  CREATE INDEX idx_prospection_request ON prospective_predictions (request_hash);
  CREATE INDEX idx_prospection_specialist ON prospective_predictions (self_id, candidate_specialist, created_at DESC);
  ```
  Test.

### Prospection step

- **AC-60.2.** `run_prospection(self_id, request, candidates)` inserts into the pipeline between spec 44's step 5 (decision extraction) and step 7 (dispatch). Input `candidates` is the set of 1-3 specialists being considered (from the perception LLM's internal reasoning or tool calls). Output: a list of `PredictionId`s. Test.
- **AC-60.3.** For each candidate, retrieve top-K similar past routings where `context.decision = "delegate"` AND `context.target = specialist` AND the outcome memory is linked (spec 44's outcome observation). Similarity by request embedding. `K_PROSPECTION = 5`. Test.
- **AC-60.4.** Build a prompt: "I'm considering routing this request to {specialist}. Here are similar past routings I did: {top-K snippets}. What do I expect to happen if I route this one the same way? Reply in under 80 tokens." Call the LLM. Parse the reply into `predicted_outcome_summary` + `predicted_confidence` (extracted from the reply or a structured-output wrapper). Test.
- **AC-60.5.** Budget: `PROSPECTION_TOKEN_BUDGET = 1500` input, `200` output per candidate, `PROSPECTION_TIMEOUT_SEC = 10`. Timeout → the prediction row is inserted with `predicted_outcome_summary = "[timeout]"`, `predicted_confidence = 0.0`. Test.
- **AC-60.6.** Prospection runs only for `delegate` decisions. `reply_directly`, `ask_clarifying`, `decline` skip prospection. Test.
- **AC-60.7.** Prospection is budgeted: at most 3 candidates per request. Extra candidates the LLM considered are dropped with a log line. Test.

### Chosen marker

- **AC-60.8.** After decision extraction, the prediction row matching the actually-chosen specialist gets `chosen = 1`. Unchosen alternatives remain with `chosen = 0`. Test.

### Surprise-delta

- **AC-60.9.** After dispatch (spec 44 step 7b), `resolve_prediction(prediction_id, actual_outcome_summary)` fills `actual_outcome_summary`, computes `surprise_delta`, sets `resolved_at`. Test.
- **AC-60.10.** `surprise_delta` is computed by a short LLM call: "You predicted: {predicted}. Actually: {actual}. On a scale of 0.0 (identical to prediction) to 1.0 (completely different), how surprised am I?" Parse the float. Budget: `SURPRISE_TOKEN_BUDGET = 300` in / `30` out. Test.
- **AC-60.11.** Surprise-delta is also recorded as the `surprise_delta` field on the dispatched request's decision memory (spec 44 AC-44.10 — the decision memory gets this field updated post-hoc). Links the prediction to its outcome memory. Test.

### Unchosen alternatives

- **AC-60.12.** For `chosen = 0` rows, `actual_outcome_summary` is never filled (we didn't actually route to that specialist). `surprise_delta` remains NULL. Test.
- **AC-60.13.** Unchosen predictions are still valuable for spec 65 — "what did I think would happen if I'd chosen the other path?" Test that they're queryable by specialist + time range.

### Memory interaction

- **AC-60.14.** A surprise-delta > `HIGH_SURPRISE_THRESHOLD = 0.5` mints a LESSON memory: `"I predicted {predicted} but got {actual}. Surprise = {delta:.2f}. This was an unexpected outcome."` Test.
- **AC-60.15.** A surprise-delta < `LOW_SURPRISE_THRESHOLD = 0.15` is quietly recorded — the prediction was accurate — no LESSON needed (high-accuracy predictions aren't surprising). Test.

### Observability

- **AC-60.16.** Prometheus histogram `turing_prospection_surprise_delta{specialist, self_id}` reports the distribution. Test.
- **AC-60.17.** Counter `turing_prospection_timeout_total`. Test.

### Edge cases

- **AC-60.18.** First request ever to a specialist — no similar past routings. Prompt becomes: "I haven't routed to {specialist} before. Guess what might happen." `predicted_confidence` should reflect the absence of priors; LLM prompt reminds it to be honest. Test.
- **AC-60.19.** A dispatched specialist raises an exception — `actual_outcome_summary` becomes `"[error] {exception_class}"`. Surprise computation handles this as distinctly from successful outcomes. Test.
- **AC-60.20.** Prospection writes go through forensic tagging (spec 39). Test.
- **AC-60.21.** Prospection respects `CONDUIT_MODE` — only runs when `"self"`. Stateless mode skips prospection. Test.
- **AC-60.22.** Prospection failure (LLM down, retrieval empty) does NOT fail the request. The request proceeds without prospection; a log entry notes the skip. Test.
- **AC-60.23.** Concurrent prospection on the same request (shouldn't happen; spec 44's advisory lock prevents) — if it does, PK collision fails the second gracefully. Test.

## Implementation

```python
# self_prospection.py

K_PROSPECTION: int = 5
PROSPECTION_TOKEN_BUDGET: int = 1500
PROSPECTION_TIMEOUT_SEC: int = 10
HIGH_SURPRISE_THRESHOLD: float = 0.5
LOW_SURPRISE_THRESHOLD: float = 0.15


async def run_prospection(
    repo, self_id: str, request: ChatRequest, candidates: list[str],
    *, llm, new_id,
) -> list[str]:
    prediction_ids: list[str] = []
    for specialist in candidates[:3]:
        similar = _retrieve_similar_routings(repo, self_id, request, specialist, K_PROSPECTION)
        try:
            prediction = await _ask_prediction(llm, request, specialist, similar)
        except LlmTimeout:
            prediction = Prediction(summary="[timeout]", confidence=0.0)
        pid = new_id("pred")
        repo.insert_prediction(ProspectivePrediction(
            id=pid,
            self_id=self_id,
            request_hash=_current_request_hash(),
            candidate_specialist=specialist,
            predicted_outcome_summary=prediction.summary,
            predicted_confidence=prediction.confidence,
            chosen=False,
            created_at=datetime.now(UTC),
        ))
        prediction_ids.append(pid)
    return prediction_ids


async def resolve_prediction(repo, prediction_id: str, actual_outcome: str,
                              *, llm) -> None:
    p = repo.get_prediction(prediction_id)
    try:
        delta = await _ask_surprise(llm, p.predicted_outcome_summary, actual_outcome)
    except LlmTimeout:
        delta = 0.5  # neutral fallback
    repo.update_prediction(prediction_id, actual_outcome=actual_outcome,
                            surprise_delta=delta, resolved_at=datetime.now(UTC))
    if delta > HIGH_SURPRISE_THRESHOLD:
        memory_bridge.mirror_lesson(
            self_id=p.self_id,
            content=(f"I predicted {p.predicted_outcome_summary!r} but got "
                     f"{actual_outcome!r}. Surprise = {delta:.2f}."),
            intent_at_time="high surprise outcome",
            context={"prediction_id": prediction_id},
        )
```

## Open questions

- **Q60.1.** 3 candidates per request × LLM call = expensive. Alternative: only prospect the chosen specialist plus one "control" (the second-ranked). Phase-1: just the chosen; Phase-2: chosen + one alternative.
- **Q60.2.** Surprise-delta is itself LLM-scored. That's subjective. A more rigorous approach compares embeddings of predicted vs actual summaries. Cheaper but less nuanced. Maybe hybrid — embedding-distance as baseline, LLM-score as refinement when embedding distance is ambiguous.
- **Q60.3.** Prospection runs BEFORE dispatch. An alternative is "after perception, the LLM already has a prediction in its own reasoning; tease that out instead of a separate call." Saves a round-trip but requires prompt-engineering changes in the perception step. Deferred.
- **Q60.4.** `actual_outcome_summary` is a small LLM-summary of the specialist's output. Long specialist outputs need summarization; the summary is lossy. Store the raw output memory id in `context` for traceback.
