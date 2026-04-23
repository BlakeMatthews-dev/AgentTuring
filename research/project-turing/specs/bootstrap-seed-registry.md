# Spec 48 — Bootstrap seed registry + signed audit (G15, G16)

*Refuse to reuse a HEXACO seed across selves without explicit opt-in; sign the bootstrap-complete memory with the operator key; verify on perception. Closes F26.*

**Depends on:** [self-bootstrap.md](./self-bootstrap.md), [persistence.md](./persistence.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** [conduit-runtime.md](./conduit-runtime.md).

---

## Current state

`run_bootstrap(..., seed=N)` produces deterministic profiles. Running twice with the same seed produces twin selves silently. The `finalize` LESSON memory is an unsigned textual record; nothing verifies its integrity on read.

## Target

1. A `self_bootstrap_seeds(seed, used_by_self_id, used_at)` registry; `run_bootstrap` refuses reuse unless `--allow-seed-reuse`.
2. The finalize LESSON memory carries an operator-key signature over its canonical form; verification on first perception places the self into `read-only` mode on tamper.

## Acceptance criteria

### Seed registry

- **AC-48.1.** New table:
  ```sql
  CREATE TABLE self_bootstrap_seeds (
      seed             INTEGER PRIMARY KEY,
      used_by_self_id  TEXT NOT NULL REFERENCES self_identity(self_id),
      used_at          TEXT NOT NULL
  );
  ```
  Test.
- **AC-48.2.** `run_bootstrap(..., seed=N)`: before anything else, inserts `(N, self_id, now)` into `self_bootstrap_seeds`. A PK collision with an existing row raises `SeedReused(N, existing_self_id)` unless `allow_seed_reuse=True`. Test both.
- **AC-48.3.** `run_bootstrap(..., seed=None)` generates a seed from `secrets.randbits(63)` and inserts. Test.
- **AC-48.4.** With `allow_seed_reuse=True`, the second bootstrap succeeds and writes an additional LESSON memory: `content = "I was bootstrapped with a seed previously used by {prior_self_id}. I may share their initial personality."`, `intent_at_time = "twin-self origin"`. Test.
- **AC-48.5.** CLI: `stronghold bootstrap-self --seed N --allow-seed-reuse` opts in. Default is refuse. Test.

### Signed audit

- **AC-48.6.** Operator key: a symmetric HMAC key loaded from `OPERATOR_SIGNING_KEY` env var at startup; must be set for `CONDUIT_MODE = "self"`. If unset, startup fails. Test.
- **AC-48.7.** The bootstrap-finalize LESSON memory's `context.signature` is computed:
  ```python
  canonical = f"{self_id}|{seed}|{created_at.isoformat()}|{content}"
  signature = hmac.new(OPERATOR_SIGNING_KEY, canonical.encode(), "sha256").hexdigest()
  ```
  Written at bootstrap-finalize time. Test.
- **AC-48.8.** `verify_bootstrap_signature(self_id)` recomputes and compares. Called once at conduit startup (spec 45 AC-45.8 addition). Mismatch raises `BootstrapTamperDetected`. Test with a tampered memory.
- **AC-48.9.** On `BootstrapTamperDetected`, the runtime enters `read-only` mode: `handle()` short-circuits with HTTP 503 and writes an OPINION memory `"bootstrap signature mismatch detected; I have been placed in read-only mode"`. Operator must rerun `stronghold self verify --force` to clear. Test.

### Key rotation

- **AC-48.10.** `stronghold self resign --old-key KEY --new-key KEY` recomputes signatures on legacy rows. Called by the operator when rotating keys. Test.

### Observability

- **AC-48.11.** Prometheus gauge `turing_self_read_only{self_id} = 0 | 1`. Test.
- **AC-48.12.** Counter `turing_bootstrap_signature_verified_total{self_id, result="ok"|"tamper"}`. Test.

### Edge cases

- **AC-48.13.** Seed 0 is legal; `INTEGER PRIMARY KEY` allows it. Test.
- **AC-48.14.** `--allow-seed-reuse` without a seed (`--seed None`) is a contradiction — raises `UsageError` before any DB work. Test.
- **AC-48.15.** Reboot path: `verify_bootstrap_signature` reads the LESSON memory from durable storage. Missing memory (DB corruption) treated as tamper. Test.
- **AC-48.16.** Bootstrap crash after seed insert but before finalize: on resume, the seed row exists; resume is allowed as long as `used_by_self_id` matches. Test.

## Implementation

```python
# self_bootstrap.py additions

class SeedReused(Exception):
    def __init__(self, seed: int, existing: str):
        self.seed = seed
        self.existing = existing


def run_bootstrap(repo, self_id, seed, ask, item_bank, new_id,
                  resume=False, overrides=None, *, allow_seed_reuse=False):
    with repo.advisory_lock(f"self:{self_id}:bootstrap"):
        if not resume:
            preflight_validate(repo, self_id)
            _reserve_seed(repo, seed, self_id, allow_seed_reuse=allow_seed_reuse)
            repo.start_bootstrap_progress(self_id, seed=seed)
            ensure_items_loaded(repo, self_id, item_bank, new_id)
            profile = draw_and_persist_facets(repo, self_id, seed, overrides, new_id)
            start_at = 1
        else:
            ...
        generate_likert_answers(...)
        _finalize_signed(repo, self_id, seed=seed)


def _reserve_seed(repo, seed: int | None, self_id: str, *, allow_seed_reuse: bool):
    actual_seed = seed if seed is not None else secrets.randbits(63)
    try:
        repo.conn.execute(
            "INSERT INTO self_bootstrap_seeds(seed, used_by_self_id, used_at) VALUES (?, ?, ?)",
            (actual_seed, self_id, _now_iso()),
        )
        repo.conn.commit()
    except sqlite3.IntegrityError:
        existing = repo.conn.execute(
            "SELECT used_by_self_id FROM self_bootstrap_seeds WHERE seed = ?",
            (actual_seed,),
        ).fetchone()[0]
        if not allow_seed_reuse:
            raise SeedReused(actual_seed, existing)
        memory_bridge.mirror_lesson(
            self_id=self_id,
            content=(f"I was bootstrapped with a seed previously used by {existing}. "
                     f"I may share their initial personality."),
            intent_at_time="twin-self origin",
        )
```

```python
# self_signing.py

def sign_bootstrap(self_id, seed, created_at, content) -> str:
    canonical = f"{self_id}|{seed}|{created_at.isoformat()}|{content}"
    return hmac.new(
        _signing_key(), canonical.encode(), hashlib.sha256,
    ).hexdigest()


def verify_bootstrap_signature(repo, self_id: str) -> None:
    mem = repo.find_bootstrap_complete_memory(self_id)  # queries durable_memory
    canonical = f"{self_id}|{mem.context['seed']}|{mem.created_at.isoformat()}|{mem.content}"
    expected = hmac.new(_signing_key(), canonical.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mem.context["signature"]):
        raise BootstrapTamperDetected(self_id)
```

## Open questions

- **Q48.1.** HMAC-SHA256 with a symmetric key is simple but requires secure storage of the key. Asymmetric (Ed25519) is more audit-friendly (verifier doesn't need the signing key) but adds deployment complexity. Start symmetric; revisit.
- **Q48.2.** On tamper, entering `read-only` is conservative. An alternative is `halt` (refuse to run at all) or `isolate` (continue serving but stop writing). Read-only is the middle ground.
- **Q48.3.** Seed registry is per-deployment. A hypothetical multi-deployment coordination layer would need cross-deployment seed dedup. Out of scope.
- **Q48.4.** `secrets.randbits(63)` fits in a signed integer for SQLite compat. 2^63 space is plenty for seed uniqueness.
