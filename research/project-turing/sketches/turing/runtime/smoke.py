"""Smoke-mode acceptance check.

Runs the system briefly with the FakeProvider + baseline scenario, then
verifies that everything an operator expects to see has actually happened:

    - tick loop ran and shut down cleanly
    - durable memory accumulated (AFFIRMATIONs from tuner)
    - journal narrative + identity files exist
    - obsidian vault has at least one note
    - metrics endpoint responded

Exits 0 on success, non-zero with a list of failures on miss.

Use this as your pre-deployment check:

    docker compose run --rm turing --smoke-test

(Container env defaults the FakeProvider so smoke needs no real LiteLLM.)
"""

from __future__ import annotations

import logging
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from .config import RuntimeConfig, load_config_from_env
from .main import build_and_run


logger = logging.getLogger("turing.runtime.smoke")


SMOKE_DURATION_SECONDS: int = 12
SMOKE_TICK_RATE: int = 100


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_smoke(*, verbose: bool = True) -> int:
    """Returns exit code: 0 = success, 1 = at least one check failed."""
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "smoke.db"
        journal_dir = tmp_path / "journal"
        vault_dir = tmp_path / "vault"
        journal_dir.mkdir()
        vault_dir.mkdir()

        metrics_port = _free_port()
        argv = [
            "--use-fake-provider",
            "--tick-rate",
            str(SMOKE_TICK_RATE),
            "--duration",
            str(SMOKE_DURATION_SECONDS),
            "--db",
            str(db_path),
            "--journal-dir",
            str(journal_dir),
            "--obsidian-vault",
            str(vault_dir),
            "--scenario",
            "baseline",
            "--metrics-port",
            str(metrics_port),
            "--metrics-bind",
            "127.0.0.1",
            "--log-level",
            "ERROR",
        ]

        if verbose:
            print(
                f"smoke: running for {SMOKE_DURATION_SECONDS}s "
                f"at {SMOKE_TICK_RATE}Hz...",
                flush=True,
            )

        # Probe the metrics endpoint mid-run from a side thread.
        metrics_seen: list[str] = []

        def _probe_metrics() -> None:
            time.sleep(SMOKE_DURATION_SECONDS // 2)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{metrics_port}/metrics", timeout=3.0
                ) as resp:
                    metrics_seen.append(resp.read().decode("utf-8"))
            except Exception as exc:
                metrics_seen.append(f"ERROR: {exc}")

        prober = threading.Thread(target=_probe_metrics, daemon=True)
        prober.start()

        try:
            rc = build_and_run(argv)
        except SystemExit as exc:
            rc = int(exc.code or 0)

        prober.join(timeout=2.0)

        # ---- Checks
        if rc != 0:
            failures.append(f"runtime exit code {rc} (expected 0)")

        narrative = journal_dir / "narrative.md"
        identity = journal_dir / "identity.md"
        if not narrative.is_file():
            failures.append(f"missing journal: {narrative}")
        if not identity.is_file():
            failures.append(f"missing identity: {identity}")

        notes = list(vault_dir.rglob("*.md"))
        if not notes:
            failures.append(f"no obsidian notes written under {vault_dir}")

        # Durable memory presence — check via direct sqlite read so we
        # don't reopen the runtime.
        import sqlite3

        if db_path.is_file():
            conn = sqlite3.connect(db_path)
            try:
                durable = conn.execute(
                    "SELECT COUNT(*) FROM durable_memory"
                ).fetchone()[0]
            finally:
                conn.close()
            if durable == 0:
                failures.append("durable_memory has zero rows after smoke run")
        else:
            failures.append(f"sqlite db not created: {db_path}")

        if not metrics_seen:
            failures.append("metrics probe did not run")
        elif metrics_seen[0].startswith("ERROR"):
            failures.append(f"metrics endpoint error: {metrics_seen[0]}")
        elif "turing_tick_count" not in metrics_seen[0]:
            failures.append("metrics endpoint missing turing_tick_count")

    if verbose:
        if failures:
            print(
                f"\nsmoke FAILED ({len(failures)} issue{'s' if len(failures) != 1 else ''}):",
                flush=True,
            )
            for f in failures:
                print(f"  - {f}", flush=True)
        else:
            print(
                "\nsmoke OK: runtime boots, persists, journals, writes obsidian, "
                "exposes metrics.",
                flush=True,
            )

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run_smoke())
