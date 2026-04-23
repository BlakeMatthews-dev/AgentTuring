# Spec 45 — Conduit-mode shim

*Config flag `CONDUIT_MODE = "stateless" | "self"` picks between the existing `chat.py` pipeline and the new `self_conduit.handle`. Default `"stateless"` during rollout. Supports F39 rollout.*

**Depends on:** [conduit-runtime.md](./conduit-runtime.md), [chat-surface.md](./chat-surface.md).
**Depended on by:** —

---

## Current state

`runtime/chat.py` exposes the request entry point. Spec 44 adds `self_conduit.handle` as a replacement. With no shim, switching requires a code replacement — not reversible per deployment.

## Target

A one-flag switch at startup. Deployments choose mode; same binary supports both. Regression test asserts `"stateless"` behavior is byte-identical to pre-Tranche-6.

## Acceptance criteria

### Config

- **AC-45.1.** `CONDUIT_MODE` is read from `turing.yaml` at startup; values in `{"stateless", "self"}`; default `"stateless"`. Invalid value raises `ConfigError`. Test.
- **AC-45.2.** Also settable via env var `TURING_CONDUIT_MODE`; env overrides YAML. Test.
- **AC-45.3.** Runtime mode is surfaced on `GET /health` JSON (`{"conduit_mode": "..."}`). Test.

### Dispatch

- **AC-45.4.** The HTTP handler reads mode once at process start and dispatches to:
  - `stateless` → existing `chat.handle_request` (unchanged).
  - `self` → `self_conduit.handle`.
  Test both modes on a fake HTTP stack.
- **AC-45.5.** Switching modes requires a process restart. No hot-reload. Documented.

### Regression gate

- **AC-45.6.** With `CONDUIT_MODE = "stateless"`, **every** existing test in `sketches/tests/` continues to pass unchanged. No test is rewritten or skipped. CI-equivalent run asserts this.
- **AC-45.7.** Output parity test: a fixture request processed in `stateless` before and after the shim lands produces byte-identical responses. Test with a golden-file harness.

### Mode validation at startup

- **AC-45.8.** On `CONDUIT_MODE = "self"` startup, the process verifies at least one `self_identity` row exists AND `_bootstrap_complete` for it. If not, startup fails with `"self mode selected but no bootstrapped self found"`. Test.
- **AC-45.9.** On `stateless` startup, no such check — the mode is backward-compatible with any repo state. Test.

### Logging

- **AC-45.10.** At process start, log `conduit_mode: {mode}` at INFO; include the selected self_id in `self` mode. Test.
- **AC-45.11.** Every request's metrics labels include `conduit_mode`. Test.

### Observability

- **AC-45.12.** Counter `turing_requests_by_mode_total{mode, status_class}` increments per request. Test.

### Edge cases

- **AC-45.13.** A half-bootstrapped self (facets present but answers missing) under `self` mode fails startup per AC-45.8. Test.
- **AC-45.14.** Mode read once at start; changes to `turing.yaml` during runtime are ignored. A `SIGHUP` does NOT reread. Test.
- **AC-45.15.** For `stateless` mode, `self_conduit.handle` is never imported (no cold-import cost). Test via lazy import.

## Implementation

```python
# runtime/main.py

def build_app(cfg: TuringConfig) -> ASGIApp:
    mode = os.environ.get("TURING_CONDUIT_MODE", cfg.conduit_mode)
    if mode not in ("stateless", "self"):
        raise ConfigError(f"invalid conduit_mode: {mode}")

    repo = Repo(cfg.db_path)
    if mode == "self":
        self_id = _verify_self_ready(repo)
        runtime = SelfRuntime(repo=repo, self_id=self_id, ...)
        handler = lambda req, auth: self_conduit.handle(req, auth, runtime)
    else:
        handler = lambda req, auth: chat.handle_request(req, auth, ...)

    log.info("conduit_mode: %s", mode)
    return _asgi(handler, mode=mode)


def _verify_self_ready(repo: Repo) -> str:
    srepo = SelfRepo(repo.conn)
    self_ids = repo.conn.execute(
        "SELECT self_id FROM self_identity WHERE archived_at IS NULL"
    ).fetchall()
    if not self_ids:
        raise StartupError("self mode selected but no bootstrapped self found")
    sid = self_ids[0][0]
    if not _bootstrap_complete(srepo, sid):
        raise StartupError(f"self {sid} is not fully bootstrapped")
    return sid
```

`/health` already reports build info; add `conduit_mode` to the payload.

## Open questions

- **Q45.1.** One self-id per deployment in `self` mode. If multiple archived-off selves exist, the first one wins. Should the operator be required to specify which via env? Defer until a real multi-self scenario.
- **Q45.2.** No hot-reload. An operator swapping modes needs a graceful restart (drain + terminate). Stronghold's deployment pattern handles this. Documented.
- **Q45.3.** Parity-golden tests add maintenance cost. Alternative: snapshot-test the first three fixture requests only. Keep minimal.
