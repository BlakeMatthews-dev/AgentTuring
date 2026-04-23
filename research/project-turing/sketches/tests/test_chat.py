"""Tests for runtime/chat.py — HTTP chat surface."""

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
from turing.runtime.chat import ChatBridge, start_chat_server
from turing.self_identity import bootstrap_self_id


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def chat_setup():
    repo = Repo(None)
    self_id = bootstrap_self_id(repo.conn)
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    bridge = ChatBridge()

    # Wire a synchronous "echo" handler so chat dispatches don't depend on
    # a real provider.
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

    def _drive_reactor_until_dispatch():
        # Tick until the action sweep dispatches the chat item.
        from turing.motivation import ACTION_CADENCE_TICKS

        for _ in range(50):
            reactor.tick(ACTION_CADENCE_TICKS)
            if not motivation.backlog:
                return
            time.sleep(0.01)

    yield port, _drive_reactor_until_dispatch
    stop()
    repo.close()


def test_post_chat_resolves_via_dispatch(chat_setup) -> None:
    port, drive = chat_setup

    def _send():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            method="POST",
            data=json.dumps({"message": "hello"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=5.0).read().decode("utf-8")

    sender = threading.Thread(target=lambda result: result.append(_send()),
                               args=([],))
    # Start sender, then drive reactor so the chat handler dispatches.
    result_holder: list[str] = []
    sender = threading.Thread(target=lambda: result_holder.append(_send()))
    sender.start()
    time.sleep(0.05)              # let the POST register
    drive()
    sender.join(timeout=5.0)

    assert sender.is_alive() is False
    assert result_holder, "no response"
    body = json.loads(result_holder[0])
    assert body["reply"] == "echo: hello"


def test_get_thoughts_returns_list(chat_setup) -> None:
    port, _ = chat_setup
    response = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/thoughts", timeout=2.0
    ).read().decode("utf-8")
    body = json.loads(response)
    assert "thoughts" in body
    assert isinstance(body["thoughts"], list)


def test_get_identity_returns_self_id(chat_setup) -> None:
    port, _ = chat_setup
    response = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/identity", timeout=2.0
    ).read().decode("utf-8")
    body = json.loads(response)
    assert "self_id" in body
    assert body["wisdom"] == []


def test_unknown_path_returns_404(chat_setup) -> None:
    port, _ = chat_setup
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/nope", timeout=2.0
        )
    assert exc_info.value.code == 404


def test_root_serves_html(chat_setup) -> None:
    port, _ = chat_setup
    response = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/", timeout=2.0
    )
    assert response.status == 200
    body = response.read().decode("utf-8")
    assert "<title>Project Turing — chat</title>" in body


def test_v1_models_lists_turing_conduit(chat_setup) -> None:
    port, _ = chat_setup
    response = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/v1/models", timeout=2.0
    )
    body = json.loads(response.read().decode("utf-8"))
    assert body["object"] == "list"
    ids = [m["id"] for m in body["data"]]
    assert "turing-conduit" in ids


def test_v1_chat_completions_openai_shape(chat_setup) -> None:
    port, drive = chat_setup

    result_holder: list[str] = []

    def _send() -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            method="POST",
            data=json.dumps(
                {
                    "model": "turing-conduit",
                    "messages": [
                        {"role": "system", "content": "you are terse"},
                        {"role": "user", "content": "hello"},
                    ],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        result_holder.append(
            urllib.request.urlopen(req, timeout=5.0).read().decode("utf-8")
        )

    sender = threading.Thread(target=_send)
    sender.start()
    time.sleep(0.05)
    drive()
    sender.join(timeout=5.0)

    assert not sender.is_alive()
    body = json.loads(result_holder[0])
    assert body["object"] == "chat.completion"
    assert body["model"] == "turing-conduit"
    assert len(body["choices"]) == 1
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "echo:" in body["choices"][0]["message"]["content"]
