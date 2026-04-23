# Spec 52 — Near-duplicate node review (G9)

*On every `note_*`, embed the new text and flag near-duplicates. Flagged rows insert but are muted in the activation graph until operator resolves. Closes F16.*

**Depends on:** [self-nodes.md](./self-nodes.md), [semantic-retrieval.md](./semantic-retrieval.md), [operator-review-gate.md](./operator-review-gate.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** —

---

## Current state

Dedup is exact-match (case/whitespace normalized). `"I love art"` and `"I care about art"` are treated as distinct passions; the self can accrete a dozen near-identical nodes over time.

## Target

On every `note_*`, compute cosine similarity of the new text's embedding against existing same-kind texts. If any pair ≥ `DUPLICATE_SIMILARITY_THRESHOLD = 0.88`:
- Insert the new row.
- Mark it `pending_merge_review = True`.
- Apply a 0.5× multiplier to its strength/activation contributions until the operator resolves.
- Write an OPINION memory for the operator's digest.

## Acceptance criteria

### Embedding lookup

- **AC-52.1.** `_embed(text)` uses the existing semantic-retrieval embedding pipeline (spec 16). Test.
- **AC-52.2.** `_nearest_neighbor(self_id, kind, text, threshold)` returns `(neighbor_id, similarity)` if any pair ≥ threshold; `None` otherwise. Uses a per-kind in-memory LRU cache of recent embeddings to avoid re-embedding every existing row; cold cache re-embeds one pass. Test cold vs warm.
- **AC-52.3.** `DUPLICATE_SIMILARITY_THRESHOLD = 0.88` in `turing.yaml`. Test default.

### Flagging

- **AC-52.4.** Schema addition: every `self_{passion,hobby,interest,preference,skill}` table gains `pending_merge_review INTEGER NOT NULL DEFAULT 0` and `similar_to_node_id TEXT` columns. Migration adds these to existing rows at `0 / NULL`. Test.
- **AC-52.5.** On insert with a detected near-dup, `pending_merge_review = 1`, `similar_to_node_id = neighbor_id`. Test.
- **AC-52.6.** Activation-graph `source_state` for a pending-merge node returns `0.5 × base_state`. Test: `strength = 0.8` with `pending_merge_review = 1` returns `source_state = 0.4` for passion.

### Mirror memory

- **AC-52.7.** On flag, mirror an OPINION memory: `content = "I noted '{new}' but it's similar to existing '{old}' (sim={similarity:.3f}); flagging for review"`, `intent_at_time = "near-dup flag"`, `context = {new_id, old_id, similarity, kind}`. Test.

### Operator resolution

- **AC-52.8.** `stronghold self dedup-ack <node_id> --keep-new|--keep-old|--keep-both`:
  - `--keep-new`: archive the old (spec 51's archive path), clear pending flag on new.
  - `--keep-old`: archive the new, no pending flag needed.
  - `--keep-both`: clear pending flag on both. Intentional decision that the two are actually distinct.
  Each produces an OBSERVATION. Test.
- **AC-52.9.** `stronghold self digest` surfaces all pending-merge rows grouped by kind. Integration with spec 46's digest. Test.

### Operator timeout

- **AC-52.10.** A pending row unacked after `DEDUP_PENDING_MAX_AGE = 30 days` auto-resolves to `--keep-both` (the lenient choice), with an OBSERVATION `"dedup review timed out; keeping both nodes"`. Test.

### Observability

- **AC-52.11.** Prometheus gauge `turing_nodes_pending_merge{kind, self_id}` per kind. Test.
- **AC-52.12.** Counter `turing_near_dup_detected_total{kind, self_id}`. Test.

### Edge cases

- **AC-52.13.** Empty-text new node with no neighbor in-kind: no flag. Test.
- **AC-52.14.** New text that matches ≥ 2 existing rows above threshold: flag with `similar_to_node_id` = highest-similarity one; list the rest in `context.other_similar`. Test.
- **AC-52.15.** An exact-match duplicate (spec 24 AC-24.1) still raises before the embedding check — dedup takes precedence. Test.
- **AC-52.16.** The 0.5× multiplier is applied as a wrapping transform in `source_state`; no change to contributor weights. Test.
- **AC-52.17.** Activation cache (spec 35) invalidates when `pending_merge_review` flips. Test.

## Implementation

```python
# self_nodes.py additions

DUPLICATE_SIMILARITY_THRESHOLD: float = 0.88


def _check_near_dup(repo, self_id: str, kind: NodeKind, text: str,
                    ) -> tuple[str | None, float]:
    neighbors = _list_by_kind(repo, self_id, kind)
    if not neighbors:
        return None, 0.0
    embed = _embed(text)
    best_id, best_sim = None, 0.0
    for n in neighbors:
        n_text = _display(n)
        sim = cosine(embed, _embed(n_text))
        if sim > best_sim:
            best_id, best_sim = n.node_id, sim
    if best_sim >= DUPLICATE_SIMILARITY_THRESHOLD:
        return best_id, best_sim
    return None, best_sim


def note_passion(repo, self_id, text, strength, new_id, contributes_to=None):
    _require_ready(repo, self_id)
    _warden_gate_self_write(text, "note passion", self_id=self_id)
    _reject_dupe_text(..., text, kind="passion")
    _evict_if_at_cap(repo, self_id, NodeKind.PASSION, text)
    _consume("new_nodes")

    neighbor, sim = _check_near_dup(repo, self_id, NodeKind.PASSION, text)
    rank = repo.max_passion_rank(self_id) + 1
    p = Passion(
        node_id=new_id("passion"),
        self_id=self_id,
        text=text,
        strength=strength,
        rank=rank,
        first_noticed_at=datetime.now(UTC),
        pending_merge_review=(neighbor is not None),
        similar_to_node_id=neighbor,
    )
    repo.insert_passion(p, acting_self_id=self_id)

    if neighbor is not None:
        memory_bridge.mirror_opinion(
            self_id=self_id,
            content=(f"I noted '{text}' but it's similar to existing "
                     f"(sim={sim:.3f}); flagging for review"),
            intent_at_time="near-dup flag",
            context={"new_id": p.node_id, "old_id": neighbor,
                     "similarity": sim, "kind": "passion"},
        )
    _wire(...)
    return p


# self_activation.py wrapper

def source_state(repo, source_id, source_kind, ctx):
    state = _base_source_state(repo, source_id, source_kind, ctx)
    if _is_pending_merge(repo, source_id, source_kind):
        state *= 0.5
    return state
```

## Open questions

- **Q52.1.** Cosine threshold 0.88 is calibrated on SBERT-style embeddings. Different backends shift the number. Per-embedding-backend default if we ever swap.
- **Q52.2.** The 0.5× muting is a "reduced-voice pending review" signal. Alternative: full mute (0×) — punishes a potentially-legitimate new nuance. 0.5× preserves signal while flagging.
- **Q52.3.** Embedding every existing same-kind text on every `note_*` could be expensive. An in-memory embedding index per self per kind is cheap at current scale; grow to ANN when nodes × kinds × selves warrants.
- **Q52.4.** Auto-resolve to `--keep-both` on timeout is lenient. Alternative: `--keep-old` (reject the newer, presumed-redundant one). Lenient is safer for the self's perspective; stricter for data hygiene.
