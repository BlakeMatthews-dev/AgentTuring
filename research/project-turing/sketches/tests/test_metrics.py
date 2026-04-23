"""Tests for runtime/metrics.py — MetricsCollector + HTTP endpoint."""

from __future__ import annotations

import socket
import time
import urllib.request

from turing.runtime.metrics import MetricsCollector, start_metrics_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_render_scalar_and_labeled() -> None:
    collector = MetricsCollector()
    collector.update(turing_tick_count=42, turing_drift_ms_p99=1.5)
    collector.set_labeled("turing_pressure", ("gemini",), 250.0)
    collector.set_labeled("turing_pressure", ("zai",), 1000.0)
    collector.set_labeled("turing_durable_memories_total", ("regret",), 3)
    collector.inc_labeled("turing_dispatch_total", ("daydream_candidate", "gemini"))

    out = collector.render()
    assert "turing_tick_count 42" in out
    assert "turing_drift_ms_p99 1.5" in out
    assert 'turing_pressure{pool="gemini"} 250.0' in out
    assert 'turing_pressure{pool="zai"} 1000.0' in out
    assert 'turing_durable_memories_total{tier="regret"} 3' in out
    assert 'turing_dispatch_total{kind="daydream_candidate",pool="gemini"} 1' in out


def test_http_endpoint_serves_metrics() -> None:
    collector = MetricsCollector()
    collector.update(turing_tick_count=7)
    port = _free_port()
    stop = start_metrics_server(collector, port=port, host="127.0.0.1")
    try:
        # Small retry loop against cold-start race.
        for _ in range(20):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics", timeout=1.0
                ) as resp:
                    body = resp.read().decode("utf-8")
                    status = resp.status
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("metrics server never became reachable")
    finally:
        stop()

    assert status == 200
    assert "turing_tick_count 7" in body


def test_http_endpoint_404_on_other_path() -> None:
    collector = MetricsCollector()
    port = _free_port()
    stop = start_metrics_server(collector, port=port, host="127.0.0.1")
    try:
        import urllib.error

        for _ in range(20):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/other", timeout=1.0
                )
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
                break
            except OSError:
                time.sleep(0.05)
    finally:
        stop()
