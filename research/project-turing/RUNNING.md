# Running Project Turing

Ops doc for the research-box runtime. Branch: `research/project-turing`.
Nothing here is wired into `src/stronghold/`.

---

## What you get when it's running

A long-lived process that, without external prompting:

- **Acts** — every significant durable memory (REGRET / ACCOMPLISHMENT /
  AFFIRMATION / WISDOM) becomes a markdown file in your Obsidian vault
  (or any directory you point it at).
- **Remembers** — durable memory in SQLite, append-only for the durable
  tiers, with full lineage (`supersedes` / `superseded_by`) and a stable
  `self_id` that survives restarts.
- **Proactively thinks** — daydream sessions burn free-tier tokens,
  contradiction detector mints LESSONs, dreaming consolidates patterns
  into WISDOM, coefficient tuner commits AFFIRMATIONs that change how
  the system values its own future actions.
- **Talks** — chat HTTP server at `:9101` with a minimal HTML UI; voice
  is a layer-on later.

You see all of it via:
- The journal: `narrative.md` + `identity.md` in `--journal-dir`.
- The Obsidian vault: dated subdirectories of markdown notes.
- The chat UI: `http://localhost:9101/`.
- The Prometheus endpoint: `http://localhost:9100/metrics`.
- The inspect CLI: `python -m turing.runtime.inspect --db <db> summarize`.

---

## Prerequisites

- Either Docker (compose plugin) or a Kubernetes cluster.
- A LiteLLM proxy you control, with whichever providers you want
  (Google, z.ai, OpenRouter, anything LiteLLM supports). A virtual key
  with budget on those models. **Or** run with `--use-fake-provider`
  to skip the LLM dependency entirely (useful for first-day smokes).

You do not need separate Gemini / z.ai / OpenRouter keys here. Project
Turing only talks to LiteLLM.

---

## Quick start (Docker)

```bash
cd research/project-turing
cp .env.example .env
# Default .env runs the FakeProvider — works without any API keys.
# To use your LiteLLM, edit .env:
#   TURING_USE_FAKE_PROVIDER=false
#   LITELLM_BASE_URL=http://litellm:4000        # or wherever
#   LITELLM_VIRTUAL_KEY=sk-...
docker compose build
docker compose up -d
```

Verify:

```bash
curl http://localhost:9100/metrics                 # metrics
open  http://localhost:9101/                       # chat UI
ls    -la $(docker volume inspect -f '{{.Mountpoint}}' \
            project-turing_turing-data)/journal    # journal files
```

Stop, persist memory:

```bash
docker compose down                # keeps the volume
docker compose up -d               # resumes with the same self_id
```

Wipe everything (fresh research instance):

```bash
docker compose down -v
```

---

## Quick start (Kubernetes)

See [`k8s/README.md`](./k8s/README.md). Short version:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/scenarios-configmap.yaml      # optional
kubectl apply -f k8s/pvc.yaml

kubectl -n turing create secret generic turing-secrets \
    --from-literal=LITELLM_VIRTUAL_KEY=sk-real-virtual-key

kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

kubectl -n turing port-forward svc/turing 9100:9100 9101:9101
```

Single replica by design. Single self per deployment. Don't share the
PVC across deployments — that's two selves with the same name and a
bad time for everyone.

---

## Quick start (no Docker, no K8s)

From `research/project-turing/sketches/`:

```bash
pip install -r requirements.txt
python -m turing.runtime.main \
    --use-fake-provider \
    --tick-rate 100 \
    --db /tmp/turing.db \
    --journal-dir /tmp/journal \
    --obsidian-vault /tmp/vault \
    --chat-port 9101 \
    --metrics-port 9100 \
    --scenario baseline
```

SIGINT / SIGTERM stops cleanly; durable memory persists in the DB file.

---

## Connecting tools

| What | Env var / flag | What it does |
|---|---|---|
| Obsidian vault | `TURING_OBSIDIAN_VAULT=/data/vault` | Every durable memory event becomes a `<date>/<time>-<slug>.md` file with YAML front-matter. Vault sync (Obsidian Sync, Syncthing, git-annex) propagates externally. |
| RSS / Atom feeds | `TURING_RSS_FEEDS=https://a/rss,https://b/atom` | Reader is registered. Wiring new RSS items into the motivation backlog is on the operator (chunk N+1 in the spec list). |
| MediaWiki writes | (scaffold; configure in `main.py`) | `MediaWikiWriter(api_url, bot_username, bot_password, page_prefix)`. Bot password from your wiki's user prefs. |
| WordPress writes | (scaffold; configure in `main.py`) | `WordPressWriter(site_url, username, application_password)`. Defaults to draft status; flip to publish if you want auto-publish. |
| Search | (scaffold; configure in `main.py`) | `SearxSearch(base_url)` against any SearXNG-compatible JSON endpoint. |
| Newsletter | (scaffold; configure in `main.py`) | `NewsletterSubscriber(endpoint, email, template)`. |

The scaffolded tools take a few lines to wire — they have clean
constructors but aren't auto-registered, because they all need
operator-specific config. To wire one, register it in
`runtime/main.py`'s `tool_registry.register(...)` block.

**Permission allowlist is structural.** A tool not registered cannot be
invoked. The `ToolRegistry.invoke()` raises `ToolNotPermitted` for any
unknown name. You can read the source of the bridge that uses tools
(`runtime/actor.py`) and see exactly which tools it might call.

---

## Talking to it

Two surfaces:

1. **Chat UI** at `http://localhost:9101/`. Type, hit send. Your message
   becomes a P1 chat item; the dispatcher's reply comes back. Quick way
   to verify the loop end-to-end.
2. **HTTP API**:
   - `POST /chat` body `{"message": "..."}` → `{"reply": "...", "message_id": "..."}`
   - `GET /thoughts?limit=20` → `{"thoughts": ["...", "..."]}`
   - `GET /identity` → `{"self_id": "...", "wisdom": [...]}`

Voice will layer on later (POST audio, GET TTS) — out of scope for now.

---

## Live metrics

`http://<host>:9100/metrics` — Prometheus text format.

| Metric | Labels | Meaning |
|---|---|---|
| `turing_tick_count` | — | Monotonic tick counter. |
| `turing_drift_ms_p99` | — | Per-tick drift p99. Healthy = < 30ms at 100 Hz. |
| `turing_pressure` | `pool` | Pressure scalar feeding motivation. |
| `turing_quota_headroom` | `pool` | Tokens remaining in the current free-tier window. |
| `turing_durable_memories_total` | `tier` | Row count in `durable_memory` per tier. |
| `turing_dispatch_total` | `kind, pool` | Dispatch count by item kind × chosen pool. |

Point Prometheus at the `turing` Service's `metrics` port; standard
scrape config. No Grafana dashboard shipped — half a day's work to
roll one if you want it.

---

## Inspecting state from the CLI

```bash
# Container:
docker compose exec turing python -m turing.runtime.inspect --db /data/turing.db summarize

# K8s:
kubectl -n turing exec deploy/turing -- \
    python -m turing.runtime.inspect --db /data/turing.db summarize

# Subcommands: summarize | dispatch-log | daydream-sessions |
#              lineage <memory_id> | pressure --metrics-url URL
```

---

## Deployment readiness checklist

Before declaring it deployed:

- [ ] LiteLLM virtual key has budget on at least one pool in
      `pools.yaml`.
- [ ] Pool model identifiers in `pools.yaml` match what your LiteLLM
      proxy actually advertises (try `curl <litellm>/v1/models` with
      your virtual key).
- [ ] Persistence: PVC mounted (K8s) or volume mounted (Compose). DB
      file at the path in `TURING_DB_PATH` survives a restart.
- [ ] Journal directory writable (`TURING_JOURNAL_DIR`).
- [ ] Obsidian vault directory writable + bind-mounted to a host path
      you can sync.
- [ ] Chat port reachable from wherever you'll talk to it. Default
      bind is `127.0.0.1` on the host; the Docker / K8s envs default to
      `0.0.0.0` for inside-container service.
- [ ] Metrics port reachable by Prometheus (or curl).
- [ ] You've decided whether the chat / metrics ports go behind an
      ingress with TLS or stay on a private network. Defaults are
      cleartext HTTP — fine for an internal cluster, not fine for the
      open internet.
- [ ] You've inspected the loaded coefficient table at least once
      (`inspect summarize` shows the most recent commitments).
- [ ] You've seen at least one `narrative.md` entry land. If 30 min in
      and the file is still empty, something is wrong; check
      `docker compose logs` or `kubectl logs`.

---

## What good running looks like

After 1+ hour with `--scenario baseline` against real LiteLLM:

```
durable_memory:
  affirmation       i_did     n≈10–30      (coefficient commitments + tuner)
  accomplishment    i_did     n≈5–25
  regret            i_did     n≈2–15
  wisdom            i_did     n≈0–3        (after the first dream session)

episodic_memory:
  observation       i_did     n=hundreds   (daydream session markers + dream markers)
  hypothesis        i_imagined n=hundreds  (real model output, not placeholders)
  lesson            i_did     n=0–5        (from contradiction detector)
  opinion           i_did     n=10–40      (from synthetic workload outcomes)
```

Obsidian vault: a dated tree of notes that reads like a diary. Each
significant moment in the self's day has its own file.

Identity: `journal/identity.md` lists every WISDOM the self has
consolidated, with intent + lineage size. This is the file you read to
understand what the system "is."

---

## Common operational situations

### Nothing in the journal

Wait — at 100 Hz the journal poll cadence is every 200 ticks (~2s). At
slower tick rates it's slower. Allow at least 30s. If still nothing,
check `docker compose logs` for "journal writing to" — if absent, the
flag wasn't set.

### Chat replies are slow / 504

Default response timeout is 30s. If the dispatcher takes longer (slow
LLM, behind backlog), you'll get 504. Either raise the timeout in
`runtime/chat.py` or speed up the queue (raise `MAX_CONCURRENT_DISPATCHES`,
lower `ACTION_CADENCE_TICKS`).

### Drift is high

`turing_drift_ms_p99` over 30ms at 100 Hz means handlers are running
slow. Likely culprit: SQLite contention. Lower the tick rate (50 Hz is
fine for research) or move the DB to faster storage.

### "no WISDOM yet"

Dreaming requires `DREAM_MIN_NEW_DURABLE` (default 5) new durable
memories since the last session. With the synthetic workload, expect
the first WISDOM after ~15–20 minutes. Lower the threshold via the
tuner if you want faster first-WISDOM during testing.

### Reset to a fresh self

```bash
docker compose down -v       # or delete and recreate the PVC for K8s
docker compose up -d
```

A new `self_id` is minted at first start; previous durable memory is
gone with the volume.

---

## Where logs go

- Docker: `docker compose logs -f turing`.
- K8s: `kubectl -n turing logs -f deploy/turing`.
- Local: stderr.

`TURING_LOG_FORMAT=json` is the default in container envs. Switch to
`plain` for human reading during development.

---

## Backing up

Single SQLite file. Easiest:

```bash
docker compose exec turing \
    python -c "import sqlite3; \
               src = sqlite3.connect('/data/turing.db'); \
               dst = sqlite3.connect('/data/backup.db'); \
               src.backup(dst); dst.close()"
docker cp turing:/data/backup.db ./turing-$(date +%F).db
```

For K8s, snapshot the PVC with whatever volume snapshotting your CSI
driver supports.

---

## Schema migrations

Not supported in the current chunks. Project Turing drops-and-reseeds
on schema changes. For long-running research instances, this is a
manual operator step. A migration verifier is in `specs/persistence.md`
but unimplemented.

---

## Voice (later)

POST `/chat` with audio (Whisper-style upload), GET `/thoughts` with
TTS render — sketched as a future surface, not built yet. The chat
HTTP API is shaped so a voice layer can sit on top without changes.
