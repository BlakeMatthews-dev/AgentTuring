"""Coverage gap filler for turing/runtime/chat.py.

Spec: _parse_limit edge cases, _openai_chat_completion_response structure,
_read_recent_narrative with/without journal_dir, ChatBridge
submit/resolve/take_reply lifecycle, POST /chat with empty message,
POST /v1/chat/completions with missing messages, POST to unknown endpoint,
GET /thoughts with limit parameter.

Acceptance criteria:
- _parse_limit handles no query string, limit parameter, invalid limit
- _openai_chat_completion_response has correct structure
- _read_recent_narrative returns empty for no journal_dir and for missing file
- ChatBridge submit/resolve/take_reply works correctly
- POST /chat with empty message returns 400
- POST /v1/chat/completions with empty messages returns 400
- POST to unknown endpoint returns 404
- GET /thoughts?limit=N parses correctly
- GET /v1/models/ (trailing slash) works
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from turing.motivation import BacklogItem, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.runtime.chat import (
    ChatBridge,
    _openai_chat_completion_response,
    _parse_limit,
    _read_recent_narrative,
    make_chat_handler,
    start_chat_server,
)
from turing.self_identity import bootstrap_self_id


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestParseLimit:
    def test_no_query_string(self) -> None:
        assert _parse_limit("/thoughts", default=20) == 20

    def test_valid_limit(self) -> None:
        assert _parse_limit("/thoughts?limit=50", default=20) == 50

    def test_limit_clamped_min(self) -> None:
        assert _parse_limit("/thoughts?limit=0", default=20) == 1

    def test_limit_clamped_max(self) -> None:
        assert _parse_limit("/thoughts?limit=999", default=20) == 500

    def test_invalid_limit_returns_default(self) -> None:
        assert _parse_limit("/thoughts?limit=abc", default=20) == 20

    def test_other_params_ignored(self) -> None:
        assert _parse_limit("/thoughts?offset=5&limit=30", default=20) == 30

    def test_no_limit_param(self) -> None:
        assert _parse_limit("/thoughts?offset=5", default=20) == 20


class TestOpenaiChatCompletionResponse:
    def test_structure(self) -> None:
        resp = _openai_chat_completion_response(request_id="test-123", reply="hello there")
        assert resp["id"] == "chatcmpl-test-123"
        assert resp["object"] == "chat.completion"
        assert resp["model"] == "turing-conduit"
        assert len(resp["choices"]) == 1
        assert resp["choices"][0]["message"]["content"] == "hello there"
        assert resp["choices"][0]["message"]["role"] == "assistant"
        assert resp["choices"][0]["finish_reason"] == "stop"
        assert "usage" in resp
        assert resp["usage"]["total_tokens"] == 0


class TestReadRecentNarrative:
    def test_no_journal_dir(self) -> None:
        assert _read_recent_narrative(None, 5) == []

    def test_missing_narrative_file(self, tmp_path) -> None:
        result = _read_recent_narrative(str(tmp_path), 5)
        assert result == []

    def test_reads_narrative_blocks(self, tmp_path) -> None:
        narrative = tmp_path / "narrative.md"
        narrative.write_text("## Block 1\ncontent1\n\n## Block 2\ncontent2\n")
        result = _read_recent_narrative(str(tmp_path), 10)
        assert len(result) == 2

    def test_respects_limit(self, tmp_path) -> None:
        narrative = tmp_path / "narrative.md"
        blocks = "\n\n".join(f"## Block {i}\ncontent{i}" for i in range(10))
        narrative.write_text(blocks)
        result = _read_recent_narrative(str(tmp_path), 3)
        assert len(result) == 3

    def test_empty_file(self, tmp_path) -> None:
        narrative = tmp_path / "narrative.md"
        narrative.write_text("")
        result = _read_recent_narrative(str(tmp_path), 5)
        assert result == []


class TestChatBridge:
    def test_submit_and_resolve(self) -> None:
        bridge = ChatBridge()
        mid, event = bridge.submit()
        assert not event.is_set()
        bridge.resolve(mid, "test reply")
        assert event.is_set()
        reply = bridge.take_reply(mid)
        assert reply == "test reply"

    def test_take_reply_twice_returns_none(self) -> None:
        bridge = ChatBridge()
        mid, event = bridge.submit()
        bridge.resolve(mid, "reply")
        assert bridge.take_reply(mid) == "reply"
        assert bridge.take_reply(mid) is None

    def test_resolve_unknown_id(self) -> None:
        bridge = ChatBridge()
        bridge.resolve("nonexistent", "reply")

    def test_take_reply_unknown_id(self) -> None:
        bridge = ChatBridge()
        assert bridge.take_reply("nonexistent") is None


@pytest.fixture
def chat_server():
    repo = Repo(None)
    self_id = bootstrap_self_id(repo.conn)
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    bridge = ChatBridge()

    def echo_dispatch(item: BacklogItem, chosen_pool: str) -> None:
        message = (item.payload or {}).get("message", "")
        bridge.resolve(item.item_id, f"echo: {message}")

    motivation.register_dispatch("chat_message", echo_dispatch)

    port = _free_port()
    stop = start_chat_server(
        motivation=motivation,
        repo=repo,
        self_id=self_id,
        bridge=bridge,
        port=port,
        host="127.0.0.1",
        response_timeout_s=2.0,
        journal_dir=None,
    )

    def _drive():
        from turing.motivation import ACTION_CADENCE_TICKS

        for _ in range(50):
            reactor.tick(ACTION_CADENCE_TICKS)
            if not motivation.backlog:
                return
            time.sleep(0.01)

    time.sleep(0.1)
    yield port, _drive
    stop()
    repo.close()


class TestChatHTTPAdditional:
    def test_post_chat_empty_message_returns_400(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            method="POST",
            data=json.dumps({"message": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400

    def test_post_chat_missing_message_returns_400(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            method="POST",
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400

    def test_post_unknown_endpoint_404(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/unknown",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 404

    def test_get_thoughts_with_limit(self, chat_server) -> None:
        port, _ = chat_server
        response = (
            urllib.request.urlopen(f"http://127.0.0.1:{port}/thoughts?limit=5", timeout=2.0)
            .read()
            .decode("utf-8")
        )
        body = json.loads(response)
        assert "thoughts" in body

    def test_get_index_html(self, chat_server) -> None:
        port, _ = chat_server
        response = urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=2.0)
        assert response.status == 200
        assert "Turing" in response.read().decode("utf-8")

    def test_v1_models_trailing_slash(self, chat_server) -> None:
        port, _ = chat_server
        response = urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models/", timeout=2.0)
        body = json.loads(response.read().decode("utf-8"))
        assert body["object"] == "list"

    def test_post_invalid_json_returns_400(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            method="POST",
            data=b"not json",
            headers={"Content-Length": "8"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400

    def test_v1_chat_completions_no_user_message(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            method="POST",
            data=json.dumps({"messages": [{"role": "system", "content": "sys"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400

    def test_v1_chat_completions_empty_messages(self, chat_server) -> None:
        port, _ = chat_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            method="POST",
            data=json.dumps({"messages": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=2.0)
        assert exc_info.value.code == 400

    def test_thoughts_with_journal(self, tmp_path, chat_server) -> None:
        port, _ = chat_server
        narrative = tmp_path / "narrative.md"
        narrative.write_text("## Entry 1\nsome thought\n")
        from turing.motivation import Motivation as M
        from turing.reactor import FakeReactor as FR
        from turing.runtime.chat import start_chat_server as scs

        repo2 = Repo(None)
        sid2 = bootstrap_self_id(repo2.conn)
        reactor2 = FakeReactor()
        mot2 = Motivation(reactor2)
        bridge2 = ChatBridge()
        port2 = _free_port()
        stop2 = scs(
            motivation=mot2,
            repo=repo2,
            self_id=sid2,
            bridge=bridge2,
            port=port2,
            host="127.0.0.1",
            response_timeout_s=1.0,
            journal_dir=str(tmp_path),
        )
        time.sleep(0.1)
        try:
            resp = (
                urllib.request.urlopen(f"http://127.0.0.1:{port2}/thoughts", timeout=2.0)
                .read()
                .decode("utf-8")
            )
            body = json.loads(resp)
            assert len(body["thoughts"]) == 1
            assert "Entry 1" in body["thoughts"][0]
        finally:
            stop2()
            repo2.close()
