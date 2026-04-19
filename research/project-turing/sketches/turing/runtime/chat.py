"""Chat HTTP interface — incoming user messages, outgoing thoughts.

Stdlib http.server. Three endpoints:

    POST /chat        — body: {"message": "..."}; queues a P1 chat item
                        and waits up to `chat_response_timeout_s` for a
                        response. Returns {"reply": "..."}.
    GET  /thoughts    — returns the most recent narrative entries
                        (up to `?limit=N`, default 20).
    GET  /identity    — returns the current WISDOM as a list.

Voice can layer on later by speaking POST /chat / GET /thoughts. The
server itself doesn't need to know about audio.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..repo import Repo
from ..types import EpisodicMemory, MemoryTier, SourceKind


logger = logging.getLogger("turing.runtime.chat")


CHAT_RESPONSE_TIMEOUT_S: float = 30.0


class ChatBridge:
    """Owns the chat-message inbox and the response future per message_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._replies: dict[str, str] = {}

    def submit(self) -> tuple[str, threading.Event]:
        message_id = str(uuid4())
        event = threading.Event()
        with self._lock:
            self._pending[message_id] = event
        return message_id, event

    def resolve(self, message_id: str, reply: str) -> None:
        with self._lock:
            event = self._pending.pop(message_id, None)
            self._replies[message_id] = reply
        if event is not None:
            event.set()

    def take_reply(self, message_id: str) -> str | None:
        with self._lock:
            return self._replies.pop(message_id, None)


def make_chat_handler(
    *,
    motivation: Motivation,
    repo: Repo,
    self_id: str,
    bridge: ChatBridge,
    response_timeout_s: float = CHAT_RESPONSE_TIMEOUT_S,
    journal_dir: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:                                       # noqa: N802
            if self.path != "/chat":
                self._respond(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid json"})
                return
            message = (payload.get("message") or "").strip()
            if not message:
                self._respond(400, {"error": "missing 'message'"})
                return

            message_id, event = bridge.submit()
            item = BacklogItem(
                item_id=message_id,
                class_=1,
                kind="chat_message",
                payload={"message": message, "self_id": self_id},
                fit={},
                readiness=lambda s: True,
                cost_estimate_tokens=512,
            )
            motivation.insert(item)

            if event.wait(timeout=response_timeout_s):
                reply = bridge.take_reply(message_id) or ""
                self._respond(200, {"reply": reply, "message_id": message_id})
            else:
                self._respond(504, {"error": "timeout", "message_id": message_id})

        def do_GET(self) -> None:                                        # noqa: N802
            if self.path.startswith("/thoughts"):
                limit = _parse_limit(self.path, default=20)
                lines = _read_recent_narrative(journal_dir, limit)
                self._respond(200, {"thoughts": lines})
                return
            if self.path == "/identity":
                wisdom = list(
                    repo.find(
                        self_id=self_id,
                        tier=MemoryTier.WISDOM,
                        source=SourceKind.I_DID,
                        include_superseded=False,
                    )
                )
                self._respond(
                    200,
                    {
                        "self_id": self_id,
                        "wisdom": [
                            {
                                "memory_id": w.memory_id,
                                "content": w.content,
                                "intent": w.intent_at_time,
                                "created_at": w.created_at.isoformat(),
                            }
                            for w in wisdom
                        ],
                    },
                )
                return
            if self.path == "/" or self.path == "/index.html":
                self._serve_html()
                return
            self._respond(404, {"error": "not found"})

        def log_message(self, fmt: str, *args: object) -> None:          # noqa: A002
            logger.debug("chat: " + fmt, *args)

        def _respond(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_html(self) -> None:
            data = _CHAT_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start_chat_server(
    *,
    motivation: Motivation,
    repo: Repo,
    self_id: str,
    bridge: ChatBridge,
    port: int,
    host: str = "127.0.0.1",
    response_timeout_s: float = CHAT_RESPONSE_TIMEOUT_S,
    journal_dir: str | None = None,
) -> Callable[[], None]:
    handler_cls = make_chat_handler(
        motivation=motivation,
        repo=repo,
        self_id=self_id,
        bridge=bridge,
        response_timeout_s=response_timeout_s,
        journal_dir=journal_dir,
    )
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever, name="turing-chat", daemon=True
    )
    thread.start()
    logger.info("chat server on http://%s:%d/", host, port)

    def _stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    return _stop


# ---- Helpers ------------------------------------------------------------


def _parse_limit(path: str, *, default: int) -> int:
    if "?" not in path:
        return default
    _, query = path.split("?", 1)
    for piece in query.split("&"):
        if piece.startswith("limit="):
            try:
                return max(1, min(500, int(piece.split("=", 1)[1])))
            except ValueError:
                return default
    return default


def _read_recent_narrative(journal_dir: str | None, limit: int) -> list[str]:
    if not journal_dir:
        return []
    from pathlib import Path

    narrative = Path(journal_dir) / "narrative.md"
    if not narrative.is_file():
        return []
    text = narrative.read_text(encoding="utf-8")
    blocks = text.split("\n## ")
    out = ["## " + b if i > 0 else b for i, b in enumerate(blocks) if b.strip()]
    return out[-limit:]


_CHAT_HTML = """<!doctype html>
<meta charset=utf-8>
<title>Project Turing — chat</title>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif;
         max-width: 720px; margin: 2em auto; padding: 0 1em;
         color: #222; background: #fafafa; }
  h1 { font-weight: 500; }
  #log { border: 1px solid #ddd; padding: 1em; min-height: 240px;
         background: white; white-space: pre-wrap;
         font-family: ui-monospace, monospace; font-size: 13px;
         margin-bottom: 1em; max-height: 60vh; overflow-y: auto; }
  .you  { color: #036; }
  .self { color: #060; }
  .err  { color: #a00; }
  form  { display: flex; gap: 0.5em; }
  input[type=text] { flex: 1; padding: 0.5em; font-size: 14px; }
  button { padding: 0.5em 1em; font-size: 14px; }
  details { margin-top: 1em; color: #666; font-size: 13px; }
</style>
<h1>Project Turing</h1>
<div id="log"></div>
<form id="f">
  <input id="m" type="text" placeholder="Say something..." autofocus required>
  <button>Send</button>
</form>
<details>
  <summary>Thoughts (last 5 narrative entries)</summary>
  <pre id="thoughts">(loading…)</pre>
</details>
<script>
const log = document.getElementById('log');
const thoughts = document.getElementById('thoughts');
function add(cls, label, text) {
  const div = document.createElement('div');
  div.className = cls;
  div.textContent = label + ': ' + text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}
async function refreshThoughts() {
  try {
    const r = await fetch('/thoughts?limit=5');
    const j = await r.json();
    thoughts.textContent = (j.thoughts || []).join('\\n\\n') || '(no narrative yet)';
  } catch (e) { thoughts.textContent = 'error: ' + e; }
}
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const m = document.getElementById('m');
  const text = m.value;
  m.value = '';
  add('you', 'you', text);
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const j = await r.json();
    if (j.reply) add('self', 'self', j.reply);
    else add('err', 'err', j.error || JSON.stringify(j));
  } catch (e) { add('err', 'err', e.toString()); }
  refreshThoughts();
});
refreshThoughts();
setInterval(refreshThoughts, 10000);
</script>
"""
