# Spec 30 — Bootstrap CLI

*One-shot CLI that gives a self its initial personality. Runs inside the Turing container or on the host against the same DB.*

**Depends on:** spec 29 (self-bootstrap), spec 23 (personality), spec 19 (LiteLLM provider).
**Supersedes (partially):** spec 29 AC-29.1 through AC-29.3 (CLI shape changed).

---

## Current state

- `run_bootstrap()` in `self_bootstrap.py` is fully implemented and tested.
- `SelfRepo` has all CRUD methods for facets, items, answers, mood, bootstrap_progress.
- `draw_bootstrap_profile()` in `self_personality.py` draws 24 truncated-normal facet scores.
- The HEXACO item bank at `config/hexaco_1000.yaml` does not exist yet.
- No CLI entry point exists.

## Target

A standalone script `python -m turing.bootstrap` that:

1. Loads config from the same env vars as the runtime (`TURING_DB_PATH`, `LITELLM_BASE_URL`, etc.)
2. Reads the 1000-item bank from `config/hexaco_1000.yaml`
3. Samples 200 items from the bank (stratified by facet, random within facet)
4. Draws 24 facet scores from truncated normal
5. Asks the LLM for 200 Likert answers with justifications (serial, cheapest pool)
6. Persists everything to the same SQLite DB the runtime uses
7. Inserts neutral mood, writes completion memory

## Acceptance criteria

### Invocation

- **AC-30.1.** `python -m turing.bootstrap --self-id <ID>` runs the full bootstrap. `--self-id` is required. Absent value prints usage and exits 1.
- **AC-30.2.** Optional flags:
  - `--seed <INT>`: RNG seed for deterministic facet draw AND item sampling. Default: random.
  - `--sample-size <INT>`: number of items to sample from the bank. Default: 200. Must be <= bank size and >= 24.
  - `--resume`: continue from last checkpoint.
  - `--dry-run`: draw facets + sample items + make one LLM canary call, then exit without writes.
- **AC-30.3.** Exit codes: 0 success, 1 validation, 2 runtime (LLM/DB error).

### 1000-item bank

- **AC-30.4.** `config/hexaco_1000.yaml` contains exactly 1000 items. Schema same as the 200-item bank: `{item_number, prompt_text, keyed_facet, reverse_scored}`.
- **AC-30.5.** Items 1-200 are the canonical HEXACO-PI-R items (facet-faithful). Items 201-1000 are additional paraphrases/variations covering all 24 facets, with roughly equal distribution (~41-42 per facet).
- **AC-30.6.** All 1000 `keyed_facet` values are valid entries in `CANONICAL_FACETS`.

### Sampling

- **AC-30.7.** Bootstrap samples `--sample-size` items from the 1000-item bank, stratified by facet: each of the 24 facets gets `floor(sample_size / 24)` items minimum, with remainder distributed randomly. Items within each facet stratum are chosen uniformly at random.
- **AC-30.8.** When `--seed` is provided, the same seed produces identical facet scores AND identical item sampling. Test: two runs with same seed produce byte-identical DB contents.
- **AC-30.9.** Sampled items are loaded into `self_personality_items` for this self_id (not shared — each self gets its own sampled set because the sample differs).

### LLM answer callable

- **AC-30.10.** Each answer call sends the item's `prompt_text` plus the 24-facet profile summary to the LLM. The prompt asks for JSON: `{"answer": <1-5>, "justification": "<text>"}`.
- **AC-30.11.** The LLM call uses the cheapest chat pool from `config/pools.yaml`. If no pools config exists, fall back to `LITELLM_BASE_URL` with model `LITELLM_MODEL` env var (default: `groq-llama31-8b-instant`).
- **AC-30.12.** Retry up to 3 times per item on parse/range failure. On 4th failure, abort with exit code 2.

### Persistence

- **AC-30.13.** All writes go to the same SQLite DB at `TURING_DB_PATH` (default `/data/turing.db`).
- **AC-30.14.** After all answers: insert neutral mood `(valence=0.0, arousal=0.3, focus=0.5)`, delete bootstrap_progress row.
- **AC-30.15.** Write a LESSON-tier episodic memory: `"I was bootstrapped on {date} with seed {seed}. Sampled {sample_size} items from {bank_size}-item bank. I have no passions, hobbies, or preferences yet."`, source=I_DID, intent="self bootstrap complete".

### Resume

- **AC-30.16.** On `--resume`, read `bootstrap_progress.last_item_number`, reconstitute profile from stored facets, re-sample items using the stored seed (so the same items come back), continue from the next uncompleted item.

### Edge cases

- **AC-30.17.** `--sample-size 1000` uses every item in the bank (no sampling needed).
- **AC-30.18.** Running bootstrap twice for the same self_id raises `AlreadyBootstrapped` (exit 1).
- **AC-30.19.** If `config/hexaco_1000.yaml` is missing, exit 2 with a clear error.

## Implementation

### File layout

```
sketches/turing/bootstrap_cli.py   ← new: argparse entry point + LLM wiring
config/hexaco_1000.yaml            ← new: 1000-item bank
```

### CLI shape (argparse, not click — project has no click dep)

```python
# sketches/turing/bootstrap_cli.py

def main(argv=None):
    parser = argparse.ArgumentParser(prog="turing.bootstrap")
    parser.add_argument("--self-id", required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    ...
```

### LLM answer callable

```python
def _make_llm_asker(base_url, virtual_key, model):
    """Return an AnswerLlm callable that hits LiteLLM."""
    def ask(item, profile):
        profile_text = "\n".join(f"  {k}: {v:.2f}" for k, v in sorted(profile.items()))
        prompt = (
            f"Your HEXACO personality profile:\n{profile_text}\n\n"
            f"Rate the following statement on a 1-5 scale "
            f"(1=strongly disagree, 5=strongly agree):\n\n"
            f'"{item.prompt_text}"\n\n'
            f'Respond ONLY with JSON: {{"answer": <1-5>, "justification": "<brief reason, max 200 chars>"}}'
        )
        # POST to LiteLLM /chat/completions, parse JSON response
        ...
    return ask
```

### Item sampling

```python
def _sample_items(bank, sample_size, rng):
    """Stratified sample: each facet gets floor(sample_size/24), remainder random."""
    from collections import defaultdict
    by_facet = defaultdict(list)
    for item in bank:
        by_facet[item["keyed_facet"]].append(item)
    
    facets = sorted(by_facet.keys())
    per_facet = sample_size // len(facets)
    remainder = sample_size - per_facet * len(facets)
    
    sampled = []
    extra_facets = rng.sample(facets, remainder) if remainder else []
    for facet in facets:
        n = per_facet + (1 if facet in extra_facets else 0)
        sampled.extend(rng.sample(by_facet[facet], min(n, len(by_facet[facet]))))
    rng.shuffle(sampled)
    return sampled
```

### Entry point registration

```python
# sketches/turing/__main__.py  — does not exist yet
# Allows: python -m turing.bootstrap --self-id <ID>
```

Actually, since the runtime uses `python -m turing.runtime.main`, the bootstrap should be a separate subcommand or a standalone script. The cleanest approach:

```bash
# Inside the container:
python -m turing.bootstrap_cli --self-id <ID>

# Or from host:
docker exec turing python -m turing.bootstrap_cli --self-id <ID>
```

## Open questions

- **Q30.1.** The 800 additional items (201-1000) are generated paraphrases of the canonical 200. They should be semantically equivalent but use different wording to reduce position/familiarity effects during retesting. Acceptable for research use.
- **Q30.2.** Sample size default of 200 matches the canonical HEXACO-PI-R length. Operators can increase to 500 or 1000 for higher-resolution personality models at proportionally higher LLM cost.
- **Q30.3.** The `--sample-size` is per-bootstrap. Weekly retests (spec 23) will sample from the same bank independently.
