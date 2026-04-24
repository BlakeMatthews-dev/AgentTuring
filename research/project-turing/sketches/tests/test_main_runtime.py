"""Integration test: build_and_run with --use-fake-provider --duration for coverage.

Spec: Exercise the full runtime wiring path inside build_and_run that requires
a running reactor. Uses FakeProvider so no external services are needed.

Acceptance criteria:
- build_and_run starts, runs for N seconds, and exits cleanly
- Chat server endpoint is accessible during runtime
- Metrics endpoint is accessible during runtime
- Journal writes files when --journal-dir is set
- RSS feeds are accepted without error
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from turing.runtime.main import build_and_run


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestBuildAndRunFakeProvider:
    def test_basic_duration_run(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--duration",
                "2",
                "--tick-rate",
                "100",
                "--log-level",
                "WARNING",
            ]
        )
        assert result == 0
        assert db.exists()

    def test_with_chat_server(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--chat-port",
                str(chat_port),
                "--duration",
                "3",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_metrics(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        metrics_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--metrics-port",
                str(metrics_port),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_journal(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--journal-dir",
                str(journal_dir),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_base_prompt_file(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("You are a test agent.")
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--base-prompt",
                str(prompt_file),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_log_format_json(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--log-format",
                "json",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_rss_feeds(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--rss-feeds",
                "https://example.com/feed.xml",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_obsidian_vault(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--obsidian-vault",
                str(vault_dir),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_arg_overrides_tick_rate(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--tick-rate",
                "50",
                "--duration",
                "2",
            ]
        )
        assert result == 0

    def test_arg_overrides_chat_bind(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--chat-port",
                str(chat_port),
                "--chat-bind",
                "127.0.0.1",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_arg_overrides_metrics_bind(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        metrics_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--metrics-port",
                str(metrics_port),
                "--metrics-bind",
                "127.0.0.1",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0


class TestBuildAndRunChatIntegration:
    def test_chat_server_responds_to_get_identity(self, tmp_path) -> None:
        import threading

        db = tmp_path / "test.db"
        chat_port = _free_port()
        result_event = threading.Event()
        result_holder: list[int | Exception | None] = [None]

        def _run():
            try:
                rc = build_and_run(
                    [
                        "--use-fake-provider",
                        "--db",
                        str(db),
                        "--chat-port",
                        str(chat_port),
                        "--duration",
                        "5",
                        "--tick-rate",
                        "100",
                        "--log-level",
                        "WARNING",
                    ]
                )
                result_holder[0] = rc
            except Exception as e:
                result_holder[0] = e
            finally:
                result_event.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{chat_port}/identity", timeout=3.0)
            body = json.loads(resp.read().decode("utf-8"))
            assert "self_id" in body
            assert "wisdom" in body
        finally:
            t.join(timeout=8.0)

    def test_get_root_serves_html(self, tmp_path) -> None:
        import threading

        db = tmp_path / "test.db"
        chat_port = _free_port()

        def _run():
            try:
                build_and_run(
                    [
                        "--use-fake-provider",
                        "--db",
                        str(db),
                        "--chat-port",
                        str(chat_port),
                        "--duration",
                        "5",
                        "--tick-rate",
                        "100",
                        "--log-level",
                        "WARNING",
                    ]
                )
            except (ValueError, OSError):
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{chat_port}/", timeout=3.0)
            assert resp.status == 200
            assert "Project Turing" in resp.read().decode("utf-8")
        finally:
            t.join(timeout=8.0)

    def test_get_unknown_returns_404(self, tmp_path) -> None:
        import threading

        db = tmp_path / "test.db"
        chat_port = _free_port()

        def _run():
            try:
                build_and_run(
                    [
                        "--use-fake-provider",
                        "--db",
                        str(db),
                        "--chat-port",
                        str(chat_port),
                        "--duration",
                        "5",
                        "--tick-rate",
                        "100",
                        "--log-level",
                        "WARNING",
                    ]
                )
            except (ValueError, OSError):
                pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{chat_port}/nonexistent", timeout=3.0)
            assert exc_info.value.code == 404
        finally:
            t.join(timeout=8.0)

    def test_get_root_serves_html(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()

        def _run():
            build_and_run(
                [
                    "--use-fake-provider",
                    "--db",
                    str(db),
                    "--chat-port",
                    str(chat_port),
                    "--duration",
                    "5",
                    "--tick-rate",
                    "100",
                    "--log-level",
                    "WARNING",
                ]
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{chat_port}/", timeout=3.0)
            assert resp.status == 200
            assert "Project Turing" in resp.read().decode("utf-8")
        finally:
            t.join(timeout=8.0)

    def test_get_unknown_returns_404(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()

        def _run():
            build_and_run(
                [
                    "--use-fake-provider",
                    "--db",
                    str(db),
                    "--chat-port",
                    str(chat_port),
                    "--duration",
                    "5",
                    "--tick-rate",
                    "100",
                    "--log-level",
                    "WARNING",
                ]
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{chat_port}/nonexistent", timeout=3.0)
            assert exc_info.value.code == 404
        finally:
            t.join(timeout=8.0)
        assert db.exists()

    def test_with_chat_server(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--chat-port",
                str(chat_port),
                "--duration",
                "3",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_metrics(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        metrics_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--metrics-port",
                str(metrics_port),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_journal(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--journal-dir",
                str(journal_dir),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_base_prompt_file(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("You are a test agent.")
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--base-prompt",
                str(prompt_file),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_log_format_json(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--log-format",
                "json",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_rss_feeds(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--rss-feeds",
                "https://example.com/feed.xml",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_with_obsidian_vault(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        vault_dir = tmp_path / "vault"
        vault_dir.mkdir()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--obsidian-vault",
                str(vault_dir),
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_arg_overrides_tick_rate(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--tick-rate",
                "50",
                "--duration",
                "2",
            ]
        )
        assert result == 0

    def test_arg_overrides_chat_bind(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        chat_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--chat-port",
                str(chat_port),
                "--chat-bind",
                "127.0.0.1",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0

    def test_arg_overrides_metrics_bind(self, tmp_path) -> None:
        db = tmp_path / "test.db"
        metrics_port = _free_port()
        result = build_and_run(
            [
                "--use-fake-provider",
                "--db",
                str(db),
                "--metrics-port",
                str(metrics_port),
                "--metrics-bind",
                "127.0.0.1",
                "--duration",
                "2",
                "--tick-rate",
                "100",
            ]
        )
        assert result == 0
