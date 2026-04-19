# Running Project Turing

This is the ops doc for the research-box runtime. The branch is
`research/project-turing`; nothing here is wired into `src/stronghold/`.

---

## Prerequisites

- Docker (compose plugin) **or** Python 3.12+ with `pip install httpx PyYAML`.
- Optional: `GEMINI_API_KEY` or `ZAI_API_KEY` if you want real LLM calls.
  Without them, the `fake` provider is used — which is still enough to exercise
  every code path; just no real daydreaming content.

---

## Quick start (Docker)

```bash
cd research/project-turing
cp .env.example .env
# Optional: edit .env and add provider API keys.
docker compose build
docker compose up -d
```

The service starts, runs forever, exposes `:9100/metrics`, and persists its
SQLite database to a Docker volume (`turing-data`). Check progress:

```bash
# Live metrics:
curl http://localhost:9100/metrics

# Summary of what the self has accumulated:
docker compose exec turing \
    python -m turing.runtime.inspect --db /data/turing.db summarize

# Recent daydream sessions with their I_IMAGINED output:
docker compose exec turing \
    python -m turing.runtime.inspect --db /data/turing.db daydream-sessions

# Walk the supersession chain for a specific memory:
docker compose exec turing \
    python -m turing.runtime.inspect --db /data/turing.db lineage <memory_id>
```

Stop and keep durable memory for next time:

```bash
docker compose down                 # stops the container, keeps the volume
docker compose up -d                # resumes with self_id intact
```

Nuke everything and start a fresh research instance:

```bash
docker compose down -v              # also removes turing-data volume
```

---

## Quick start (no Docker)

From `research/project-turing/sketches/`:

```bash
pip install -r requirements.txt
python -m turing.runtime.main \
    --tick-rate 100 \
    --db /tmp/turing.db \
    --providers fake \
    --scenario baseline \
    --metrics-port 9100
```

SIGINT / SIGTERM stops cleanly; durable memory persists in the DB file.

---

## Inspecting state

The `turing.runtime.inspect` CLI reads the SQLite database directly (no IPC
to the running process). Subcommands:

| Command | What it shows |
|---|---|
| `summarize` | Counts by tier + source; self_id; recent REGRETs, ACCOMPLISHMENTs, coefficient commitments. |
| `dispatch-log --limit N` | Recent `I_DID / OBSERVATION` markers (includes daydream session markers). |
| `daydream-sessions --limit N` | Each session marker with the I_IMAGINED outputs it produced. |
| `lineage <memory_id>` | Walks `supersedes` backward and `superseded_by` forward. |
| `pressure --metrics-url URL` | Scrapes live pressure from a running metrics endpoint. |

---

## Live metrics

The Prometheus endpoint (when `TURING_METRICS_PORT` is set) exposes:

| Metric | Labels | Meaning |
|---|---|---|
| `turing_tick_count` | — | Monotonic tick counter. |
| `turing_drift_ms_p99` | — | p99 of observed per-tick drift in ms. |
| `turing_pressure` | `pool` | Per-pool pressure scalar feeding motivation. |
| `turing_quota_headroom` | `pool` | Tokens remaining in the current window. |
| `turing_durable_memories_total` | `tier` | Row count in durable_memory per tier. |
| `turing_daydream_sessions_total` | `pool` | Session markers emitted per pool. |
| `turing_dispatch_total` | `kind`, `pool` | Dispatch count by item kind × chosen pool. |

You can point Prometheus at `http://<host>:9100/metrics` or just `curl` it.
No Grafana dashboard shipped — rolling one is a half-day job if you want it.

---

## Common operational situations

### "Why is nothing happening?"

Check pressure and the scenario:

```bash
curl http://localhost:9100/metrics | grep turing_pressure
docker compose logs turing | tail -20
```

If pressure is 0 on all pools, no providers have headroom or the quota
tracker hasn't been wired for your chosen providers.

If pressure is nonzero but no daydream sessions appear, the dynamic_priority
curve may be under the DAYDREAM_FIRE_FLOOR; look at `inspect summarize`'s
recent coefficient commitments — the tuner may have raised the floor.

### "Why is drift so high?"

`turing_drift_ms_p99` on a research box will drift more than main's Reactor
because handlers aren't O(1)-audited and metrics refreshes hit SQLite. At
100 Hz, 10–30 ms drift is normal. Tuning knobs:

- Lower the tick rate (`TURING_TICK_RATE_HZ=20` is fine for research).
- Disable metrics (`unset TURING_METRICS_PORT`).
- Profile specific handlers if one is dominant.

### "Rate limits from Gemini / z.ai"

Expected. The provider raises `RateLimited`; the daydream / contradiction /
tuner dispatch catches and logs. No crash; pass is skipped. Use
`turing_quota_headroom{pool="gemini"} == 0` to confirm.

If rate limits are constant, the quota-tracker assumptions in
`runtime/providers/gemini.py` or `zai.py` may be wrong for your tier.
Adjust `tokens_allowed_per_window` and `window_duration` in the provider
constructor or subclass.

### "How do I back up the database?"

```bash
# In the container:
docker compose exec turing \
    python -c "import sqlite3; \
               src = sqlite3.connect('/data/turing.db'); \
               dst = sqlite3.connect('/data/backup.db'); \
               src.backup(dst); dst.close()"

# From the host:
docker cp turing:/data/backup.db ./turing-$(date +%F).db
```

### "Can I do schema migrations?"

Not supported in chunks 1–5. Project Turing drops-and-reseeds when the schema
changes. For a long-running research instance, that's a manual operator step.
A proper migration verifier is in the durable-memory spec (§persistence.md)
but not yet implemented.

---

## Where logs go

- Docker: `docker compose logs turing` or `-f` to follow.
- Non-Docker: stderr of the `python -m turing.runtime.main` process.

`TURING_LOG_FORMAT=json` is the default in Docker. Set `plain` for human-
readable output during development.

---

## What good running looks like

After 1+ hour with `--scenario baseline` on the fake provider:

```
durable_memory:
  affirmation       i_did     n≈10-30       (coefficient commitments + policy)
  accomplishment    i_did     n≈5-20
  regret            i_did     n≈2-15

episodic_memory:
  observation       i_did     n≈300+        (daydream session markers)
  hypothesis        i_imagined n≈300+       (daydreamed what-ifs)
  lesson            i_did     n≈0-3         (from contradiction detector)
  opinion           i_did     n≈5-20        (synthetic stance/REGRET pairs)
```

After 1+ hour with real Gemini and `contradiction-injection`:

- `turing_quota_headroom{pool="gemini"}` drifts downward across each minute,
  resets at the RPM window boundary.
- `turing_daydream_sessions_total{pool="gemini"}` climbs.
- Real hypothesis content in `inspect daydream-sessions` — no longer
  placeholder strings.
