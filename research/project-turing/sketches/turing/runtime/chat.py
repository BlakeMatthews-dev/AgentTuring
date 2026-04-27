"""Chat HTTP interface — incoming user messages, outgoing thoughts.

Stdlib http.server. Endpoints:

    POST /chat                — body: {"message": "..."}; queues a P1 chat item
                                and waits for a response. Returns {"reply": "..."}.
    POST /feedback            — body: {"message_id": "...", "rating": "up"|"down"}
                                awards thumbs up/down points.
    GET  /rewards             — returns current point totals.
    GET  /thoughts            — returns the most recent narrative entries.
    GET  /identity            — returns the current WISDOM as a list.

Voice can layer on later by speaking POST /chat / GET /thoughts. The
server itself doesn't need to know about audio.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from ..motivation import BacklogItem, Motivation
from ..rewards import RewardTracker
from ..repo import Repo
from ..types import EpisodicMemory, MemoryTier, SourceKind


logger = logging.getLogger("turing.runtime.chat")


CHAT_RESPONSE_TIMEOUT_S: float = 90.0
MAX_REQUEST_BODY_BYTES: int = 20 << 20  # 20 MiB


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


TURING_MODEL_ID: str = "turing-conduit"


SENTINEL_KINDS = frozenset(
    {
        "journal",
        "notebook",
        "blog",
        "draft",
        "letter",
        "voice",
        "remember",
        "opinion",
        "goal",
        "hypothesis",
        "regret",
        "read-code",
        "request-change",
        "image",
    }
)

_SENTINEL_RE = re.compile(
    r"```(" + "|".join(SENTINEL_KINDS) + r") *\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def _apply_sentinels(
    reply: str,
    on_sentinel: Callable[[str, str], None] | None,
) -> str:
    """Find sentinel blocks, fire the handler, replace with collapsed HTML."""
    if on_sentinel is None:
        return reply

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        kind = m.group(1).lower()
        content = m.group(2).strip()
        if not content:
            return m.group(0)
        try:
            on_sentinel(kind, content)
        except Exception:
            logger.exception("sentinel handler failed for kind=%s", kind)
        first_line = content.split("\n")[0][:80]
        return (
            f"<details><summary>✍ {kind} — {first_line}</summary>\n\n"
            f"```\n{content}\n```\n\n</details>"
        )

    return _SENTINEL_RE.sub(_replace, reply)


def make_chat_handler(
    *,
    motivation: Motivation,
    repo: Repo,
    self_id: str,
    bridge: ChatBridge,
    response_timeout_s: float = CHAT_RESPONSE_TIMEOUT_S,
    journal_dir: str | None = None,
    reward_tracker: RewardTracker | None = None,
    base_prompt_path: str | None = None,
    on_sentinel: Callable[[str, str], None] | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            # OpenAI-compatible: POST /v1/chat/completions
            # so OpenWebUI (or anything else speaking the OpenAI API) can
            # add Project Turing as a model and chat through it normally.
            if self.path.rstrip("/") == "/v1/chat/completions":
                return self._handle_openai_chat_completions()
            # Backwards-compat simple endpoint for the built-in HTML UI.
            if self.path == "/chat":
                return self._handle_simple_chat()
            if self.path == "/feedback":
                return self._handle_feedback()
            self._respond(404, {"error": "not found"})

        def _read_json(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_REQUEST_BODY_BYTES:
                self._respond(413, {"error": "request body too large"})
                return None
            try:
                raw = self.rfile.read(length).decode("utf-8") or "{}"
                return dict(json.loads(raw))
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid json"})
                return None

        def _dispatch_and_wait(
            self,
            *,
            latest_user_message: str,
            history: list[dict[str, Any]] | None = None,
            conversation_id: str | None = None,
            chat_user: str | None = None,
        ) -> tuple[str, str] | None:
            """Submit a chat P1 item and wait for the reply. Returns
            (message_id, reply) or None if the request timed out."""
            message_id, event = bridge.submit()
            payload: dict[str, Any] = {
                "message": latest_user_message,
                "history": history or [],
                "self_id": self_id,
                "conversation_id": conversation_id,
            }
            if chat_user:
                payload["chat_user"] = chat_user
            item = BacklogItem(
                item_id=message_id,
                class_=1,
                kind="chat_message",
                payload=payload,
                fit={},
                readiness=lambda s: True,
                cost_estimate_tokens=512,
            )
            motivation.insert(item)
            if not event.wait(timeout=response_timeout_s):
                return None
            return message_id, (bridge.take_reply(message_id) or "")

        def _handle_simple_chat(self) -> None:
            payload = self._read_json()
            if payload is None:
                return
            message = (payload.get("message") or "").strip()
            if not message:
                self._respond(400, {"error": "missing 'message'"})
                return
            chat_user = payload.get("user") or None
            result = self._dispatch_and_wait(
                latest_user_message=message, history=[], chat_user=chat_user
            )
            if result is None:
                self._respond(504, {"error": "timeout"})
                return
            message_id, reply = result
            self._respond(200, {"reply": reply, "message_id": message_id})

        def _handle_openai_chat_completions(self) -> None:
            payload = self._read_json()
            if payload is None:
                return
            messages = payload.get("messages") or []
            if not isinstance(messages, list) or not messages:
                self._respond(400, {"error": "missing 'messages'"})
                return

            stream = bool(payload.get("stream", False))

            # Prefer an explicit stable ID from the client (OpenWebUI sends
            # `chat_id`).  Fall back to a per-request UUID — intentionally NOT
            # hashing message content, because short openers like "Hi" collide
            # across sessions and cause the session index to cross-contaminate.
            conv_id: str | None = None
            raw_conv = payload.get("chat_id") or payload.get("conversation_id")
            if raw_conv and isinstance(raw_conv, str):
                conv_id = raw_conv
            else:
                conv_id = "c-" + str(uuid4()).replace("-", "")[:16]

            latest = ""
            history: list[dict[str, Any]] = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "user")
                raw_content = msg.get("content", "")
                # Support both plain string and OpenAI array-of-parts format.
                if isinstance(raw_content, list):
                    content = " ".join(
                        part.get("text", "")
                        for part in raw_content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ).strip()
                elif isinstance(raw_content, str):
                    content = raw_content
                else:
                    continue
                if not content:
                    continue
                history.append({"role": role, "content": content})
                if role == "user":
                    latest = content
            if not latest:
                self._respond(400, {"error": "no user message"})
                return
            if history and history[-1]["role"] == "user":
                history = history[:-1]

            result = self._dispatch_and_wait(
                latest_user_message=latest,
                history=history,
                conversation_id=conv_id,
                chat_user=payload.get("user"),
            )
            if result is None:
                if stream:
                    self._respond_stream_error("timeout")
                else:
                    self._respond(504, {"error": "timeout"})
                return
            message_id, reply = result
            reply = _apply_sentinels(reply, on_sentinel)
            if stream:
                self._respond_stream(message_id=message_id, reply=reply)
            else:
                self._respond(
                    200,
                    _openai_chat_completion_response(request_id=message_id, reply=reply),
                )

        def _handle_feedback(self) -> None:
            if reward_tracker is None:
                self._respond(501, {"error": "reward system not configured"})
                return
            payload = self._read_json()
            if payload is None:
                return
            message_id = (payload.get("message_id") or "").strip()
            rating = (payload.get("rating") or "").strip().lower()
            if not message_id:
                self._respond(400, {"error": "missing 'message_id'"})
                return
            if rating not in ("up", "down"):
                self._respond(400, {"error": "rating must be 'up' or 'down'"})
                return
            if reward_tracker.has_feedback(message_id):
                self._respond(409, {"error": "feedback already submitted for this message"})
                return
            event_type = "thumbs_up" if rating == "up" else "thumbs_down"
            points = reward_tracker.award(
                interface="chat",
                item_id=message_id,
                event_type=event_type,
            )
            total = reward_tracker.total_points()
            self._respond(200, {"points": points, "total_points": total, "event_type": event_type})

        def _respond_stream(self, *, message_id: str, reply: str) -> None:
            """Emit a single-chunk SSE stream for the full reply."""
            created = int(time.time())
            chunk_id = f"chatcmpl-{message_id}"

            def _sse(obj: dict[str, Any]) -> bytes:
                return ("data: " + json.dumps(obj) + "\n\n").encode("utf-8")

            role_chunk = _sse(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": TURING_MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            content_chunk = _sse(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": TURING_MODEL_ID,
                    "choices": [{"index": 0, "delta": {"content": reply}, "finish_reason": None}],
                }
            )
            finish_chunk = _sse(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": TURING_MODEL_ID,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            done_line = b"data: [DONE]\n\n"

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for part in (role_chunk, content_chunk, finish_chunk, done_line):
                    self.wfile.write(part)
                self.wfile.flush()
            except BrokenPipeError:
                logger.debug("client disconnected during stream")

        def _respond_stream_error(self, message: str) -> None:
            error_chunk = (
                "data: "
                + json.dumps({"error": {"message": message, "type": "server_error"}})
                + "\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(error_chunk)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except BrokenPipeError:
                logger.debug("client disconnected during stream error")

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                self._respond(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": TURING_MODEL_ID,
                                "object": "model",
                                "created": int(time.time()),
                                "owned_by": "project-turing",
                            }
                        ],
                    },
                )
                return
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
            if self.path == "/rewards":
                if reward_tracker is None:
                    self._respond(200, {"total_points": 0, "by_interface": {}})
                    return
                self._respond(
                    200,
                    {
                        "total_points": reward_tracker.total_points(),
                        "by_interface": reward_tracker.points_by_interface(),
                        "recent": reward_tracker.recent_events(10),
                    },
                )
                return
            if self.path == "/prompt":
                self._serve_prompt_editor()
                return
            if self.path == "/" or self.path == "/index.html":
                self._serve_html()
                return
            self._respond(404, {"error": "not found"})

        def do_PUT(self) -> None:  # noqa: N802
            if self.path == "/prompt":
                return self._handle_save_prompt()
            self._respond(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            logger.debug("chat: " + format, *args)

        def _respond(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                logger.debug("client disconnected before response sent")

        def _serve_html(self) -> None:
            data = _CHAT_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                logger.debug("client disconnected before html sent")

        def _serve_prompt_editor(self) -> None:
            current = _read_prompt_file(base_prompt_path)
            html = _PROMPT_EDITOR_HTML.replace(
                "{{CURRENT_PROMPT}}",
                current.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
            )
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                logger.debug("client disconnected before prompt editor sent")

        def _handle_save_prompt(self) -> None:
            if not base_prompt_path:
                self._respond(501, {"error": "no prompt file configured"})
                return
            payload = self._read_json()
            if payload is None:
                return
            content = (payload.get("content") or "").strip()
            if not content:
                self._respond(400, {"error": "prompt cannot be empty"})
                return
            from pathlib import Path

            Path(base_prompt_path).write_text(content, encoding="utf-8")
            logger.info("base prompt updated via /prompt endpoint")
            self._respond(200, {"status": "saved", "length": len(content)})

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
    reward_tracker: RewardTracker | None = None,
    base_prompt_path: str | None = None,
    on_sentinel: Callable[[str, str], None] | None = None,
) -> Callable[[], None]:
    handler_cls = make_chat_handler(
        motivation=motivation,
        repo=repo,
        self_id=self_id,
        bridge=bridge,
        response_timeout_s=response_timeout_s,
        journal_dir=journal_dir,
        reward_tracker=reward_tracker,
        base_prompt_path=base_prompt_path,
        on_sentinel=on_sentinel,
    )
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name="turing-chat", daemon=True)
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


def _openai_chat_completion_response(*, request_id: str, reply: str) -> dict[str, Any]:
    """OpenAI chat-completion response envelope.

    Enough for OpenWebUI and anything speaking the OpenAI API to accept
    it as a real completion. Does not report usage; upstream consumers
    shouldn't trust it for billing, only for plumbing.
    """
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": TURING_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


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


def _read_prompt_file(path: str | None) -> str:
    if not path:
        return ""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


_CHAT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset=utf-8>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Turing — field notes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@300;400;500&family=IBM+Plex+Serif:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
:root {
  --pn-ink-0:#050507; --pn-ink-1:#0A0B0A; --pn-ink-2:#0F1110;
  --pn-line-1:#232925; --pn-line-2:#334038;
  --pn-grey-1:#6E7670; --pn-grey-2:#8F9692; --pn-grey-3:#B4BAB7; --pn-grey-4:#D6D4CE;
  --pn-bone-0:#F2F0EA; --pn-bone-1:#ECEAE3;
  --pn-phosphor-hi:#A8FF8E; --pn-phosphor:#5EE88C; --pn-phosphor-dim:#1E7A3D;
  --pn-phosphor-ink:#061007;
  --pn-amber:#FFB547;
  --pn-burn:#FF5A4E;
  --pn-glow:0 0 2px rgba(94,232,140,.55),0 0 8px rgba(94,232,140,.32);
  --pn-glow-med:0 0 2px rgba(94,232,140,.8),0 0 10px rgba(94,232,140,.5),0 0 22px rgba(94,232,140,.22);
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--pn-ink-1);color:var(--pn-bone-1);
  font-family:'IBM Plex Serif',Georgia,serif;
  -webkit-font-smoothing:antialiased;
  display:flex;flex-direction:column;min-height:100vh;
}
::selection{background:var(--pn-phosphor);color:var(--pn-ink-0)}

/* ---- Masthead ---- */
.pn-masthead{
  border-bottom:1px solid var(--pn-line-2);
  padding:28px 40px 18px;
  display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:16px;
}
.pn-classification{
  font-family:'IBM Plex Mono',monospace;font-size:10px;
  letter-spacing:.32em;text-transform:uppercase;
  color:var(--pn-amber);margin-bottom:6px;
}
.pn-site-title{
  font-family:'VT323','IBM Plex Mono',monospace;
  font-size:clamp(36px,6vw,64px);line-height:.95;
  letter-spacing:.02em;text-transform:uppercase;
  color:var(--pn-phosphor-hi);text-shadow:var(--pn-glow-med);
}
.pn-points{
  font-family:'IBM Plex Mono',monospace;font-size:11px;
  letter-spacing:.18em;color:var(--pn-grey-2);text-transform:uppercase;
}
.pn-points b{color:var(--pn-phosphor);text-shadow:var(--pn-glow);font-weight:500}

/* ---- Log ---- */
#log{
  flex:1;padding:20px 40px;overflow-y:auto;max-height:calc(100vh - 260px);
  font-family:'IBM Plex Serif',serif;font-size:15px;line-height:1.7;
}
.msg-row{
  margin-bottom:14px;padding:10px 14px;
  border-left:2px solid transparent;
}
.msg-row.you{
  border-left-color:var(--pn-grey-1);
  color:var(--pn-grey-3);
}
.msg-row.self{
  border-left-color:var(--pn-phosphor);
  background:rgba(94,232,140,.04);
  color:var(--pn-bone-1);
}
.msg-row.err{
  border-left-color:var(--pn-burn);
  color:var(--pn-burn);
}
.msg-label{
  font-family:'IBM Plex Mono',monospace;font-size:10px;
  letter-spacing:.2em;text-transform:uppercase;
  color:var(--pn-grey-1);margin-bottom:4px;
}
.msg-row.self .msg-label{color:var(--pn-phosphor);text-shadow:var(--pn-glow)}
.msg-text{white-space:pre-wrap}

/* ---- Feedback buttons ---- */
.feedback{
  display:inline-flex;align-items:center;gap:6px;
  margin-top:8px;padding-top:6px;
  border-top:1px dashed var(--pn-line-1);
}
.feedback button{
  font-family:'IBM Plex Mono',monospace;font-size:11px;
  letter-spacing:.1em;text-transform:uppercase;
  background:transparent;border:1px solid var(--pn-line-2);
  color:var(--pn-grey-2);padding:3px 10px;cursor:pointer;
  transition:all 120ms;
}
.feedback button:hover{
  border-color:var(--pn-phosphor);color:var(--pn-phosphor);
  text-shadow:var(--pn-glow);
}
.feedback button.active-up{
  border-color:var(--pn-phosphor);color:var(--pn-phosphor-hi);
  background:rgba(94,232,140,.1);text-shadow:var(--pn-glow);
}
.feedback button.active-down{
  border-color:var(--pn-burn);color:var(--pn-burn);
  background:rgba(255,90,78,.08);
}
.feedback .pts{
  font-family:'IBM Plex Mono',monospace;font-size:10px;
  letter-spacing:.15em;color:var(--pn-grey-1);margin-left:4px;
}
.feedback .pts.positive{color:var(--pn-phosphor);text-shadow:var(--pn-glow)}
.feedback .pts.negative{color:var(--pn-burn)}

/* ---- Input ---- */
.pn-input-bar{
  border-top:1px solid var(--pn-line-2);
  padding:14px 40px;display:flex;gap:10px;
  background:var(--pn-ink-0);
}
.pn-input-bar input[type="text"]{
  flex:1;background:var(--pn-ink-2);border:1px solid var(--pn-line-2);
  color:var(--pn-bone-1);font-family:'IBM Plex Serif',serif;font-size:14px;
  padding:10px 14px;outline:none;
}
.pn-input-bar input[type="text"]::placeholder{color:var(--pn-grey-1)}
.pn-input-bar input[type="text"]:focus{border-color:var(--pn-phosphor)}
.pn-input-bar button{
  font-family:'IBM Plex Mono',monospace;font-size:11px;
  letter-spacing:.22em;text-transform:uppercase;
  background:var(--pn-phosphor);color:var(--pn-ink-0);border:0;
  padding:10px 20px;cursor:pointer;box-shadow:var(--pn-glow-med);
}
.pn-input-bar button:hover{background:var(--pn-phosphor-hi)}

/* ---- Thoughts drawer ---- */
.pn-thoughts{
  border-top:1px solid var(--pn-line-2);padding:14px 40px;
  font-family:'IBM Plex Mono',monospace;font-size:12px;
  color:var(--pn-grey-1);line-height:1.6;
}
.pn-thoughts summary{
  letter-spacing:.2em;text-transform:uppercase;cursor:pointer;
  color:var(--pn-grey-2);
}
.pn-thoughts summary:hover{color:var(--pn-phosphor)}
.pn-thoughts pre{
  margin-top:10px;white-space:pre-wrap;
  color:var(--pn-grey-3);font-size:12px;max-height:200px;overflow-y:auto;
}

/* ---- Scrollbar ---- */
::-webkit-scrollbar{width:8px}
::-webkit-scrollbar-thumb{background:var(--pn-line-2)}
::-webkit-scrollbar-thumb:hover{background:var(--pn-phosphor-dim)}
::-webkit-scrollbar-track{background:transparent}
</style>
</head>
<body>
<header class="pn-masthead">
  <div>
    <div class="pn-classification">AT-01 &middot; field terminal</div>
    <div class="pn-site-title">Turing</div>
  </div>
  <div class="pn-points">reward balance: <b id="pts">0</b> pts</div>
</header>
<div id="log"></div>
<form id="f" class="pn-input-bar">
  <input id="m" type="text" placeholder="transmit..." autofocus required>
  <button type="submit">send</button>
</form>
<details class="pn-thoughts">
  <summary>field notes (recent narrative)</summary>
  <pre id="thoughts">(listening...)</pre>
</details>
<script>
const log = document.getElementById('log');
const thoughts = document.getElementById('thoughts');
const ptsEl = document.getElementById('pts');

function add(cls, label, text, messageId) {
  const row = document.createElement('div');
  row.className = cls + ' msg-row';
  const lbl = document.createElement('div');
  lbl.className = 'msg-label';
  lbl.textContent = label;
  row.appendChild(lbl);
  const span = document.createElement('div');
  span.className = 'msg-text';
  span.textContent = text;
  row.appendChild(span);
  if (cls === 'self' && messageId) {
    const fb = document.createElement('div');
    fb.className = 'feedback';
    fb.dataset.mid = messageId;
    const upBtn = document.createElement('button');
    upBtn.className = 'fb-up';
    upBtn.textContent = '+ approve';
    upBtn.title = 'Thumbs up (+10 pts)';
    const downBtn = document.createElement('button');
    downBtn.className = 'fb-down';
    downBtn.textContent = '- reject';
    downBtn.title = 'Thumbs down (-20 pts)';
    const ptsSpan = document.createElement('span');
    ptsSpan.className = 'pts';
    fb.appendChild(upBtn);
    fb.appendChild(downBtn);
    fb.appendChild(ptsSpan);
    row.appendChild(fb);
  }
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function handleFeedback(btn, rating) {
  const fb = btn.closest('.feedback');
  const mid = fb.dataset.mid;
  if (!mid) return;
  const upBtn = fb.querySelector('.fb-up');
  const downBtn = fb.querySelector('.fb-down');
  const ptsSpan = fb.querySelector('.pts');
  if (upBtn.classList.contains('active-up') || downBtn.classList.contains('active-down')) return;
  fetch('/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message_id: mid, rating: rating}),
  }).then(r => r.json()).then(j => {
    if (j.points !== undefined) {
      if (rating === 'up') upBtn.classList.add('active-up');
      else downBtn.classList.add('active-down');
      ptsSpan.textContent = (j.points > 0 ? '+' : '') + j.points + ' pts';
      ptsSpan.classList.add(j.points > 0 ? 'positive' : 'negative');
      ptsEl.textContent = j.total_points;
    } else {
      ptsSpan.textContent = j.error || 'error';
    }
  }).catch(() => { ptsSpan.textContent = 'err'; });
}

log.addEventListener('click', e => {
  if (e.target.classList.contains('fb-up')) handleFeedback(e.target, 'up');
  if (e.target.classList.contains('fb-down')) handleFeedback(e.target, 'down');
});

function refreshThoughts() {
  fetch('/thoughts?limit=5').then(r => r.json()).then(j => {
    thoughts.textContent = (j.thoughts || []).join('\\n\\n') || '(no narrative yet)';
  }).catch(() => { thoughts.textContent = '(error)'; });
}

function refreshPoints() {
  fetch('/rewards').then(r => r.json()).then(j => {
    ptsEl.textContent = j.total_points || 0;
  }).catch(() => {});
}

document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const m = document.getElementById('m');
  const text = m.value;
  m.value = '';
  add('you', 'you', text, null);
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const j = await r.json();
    if (j.reply) add('self', 'self', j.reply, j.message_id);
    else add('err', 'err', j.error || JSON.stringify(j), null);
  } catch (e) { add('err', 'err', e.toString(), null); }
  refreshThoughts();
});
refreshThoughts();
refreshPoints();
setInterval(refreshThoughts, 10000);
setInterval(refreshPoints, 10000);
</script>
</body>
</html>
"""

_PROMPT_EDITOR_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset=utf-8>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Turing — base prompt</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@300;400;500&family=IBM+Plex+Serif:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
:root {
  --pn-ink-0:#050507; --pn-ink-1:#0A0B0A; --pn-ink-2:#0F1110;
  --pn-line-1:#232925; --pn-line-2:#334038;
  --pn-grey-1:#6E7670; --pn-grey-2:#8F9692; --pn-grey-3:#B4BAB7;
  --pn-bone-0:#F2F0EA; --pn-bone-1:#ECEAE3;
  --pn-phosphor-hi:#A8FF8E; --pn-phosphor:#5EE88C; --pn-phosphor-dim:#1E7A3D;
  --pn-phosphor-ink:#061007;
  --pn-amber:#FFB547;
  --pn-burn:#FF5A4E;
  --pn-glow:0 0 2px rgba(94,232,140,.55),0 0 8px rgba(94,232,140,.32);
  --pn-glow-med:0 0 2px rgba(94,232,140,.8),0 0 10px rgba(94,232,140,.5),0 0 22px rgba(94,232,140,.22);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--pn-ink-1);color:var(--pn-bone-1);font-family:'IBM Plex Serif',Georgia,serif;-webkit-font-smoothing:antialiased;padding:40px;max-width:800px;margin:0 auto}
::selection{background:var(--pn-phosphor);color:var(--pn-ink-0)}
.classification{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.32em;text-transform:uppercase;color:var(--pn-amber);margin-bottom:6px}
h1{font-family:'VT323','IBM Plex Mono',monospace;font-size:clamp(32px,5vw,52px);letter-spacing:.02em;text-transform:uppercase;color:var(--pn-phosphor-hi);text-shadow:var(--pn-glow-med);margin-bottom:8px}
.subtitle{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.18em;color:var(--pn-grey-2);text-transform:uppercase;margin-bottom:32px}
textarea{
  width:100%;min-height:50vh;background:var(--pn-ink-2);border:1px solid var(--pn-line-2);
  color:var(--pn-bone-1);font-family:'IBM Plex Mono',monospace;font-size:13px;line-height:1.7;
  padding:16px;outline:none;resize:vertical;
}
textarea:focus{border-color:var(--pn-phosphor)}
.bar{display:flex;align-items:center;gap:16px;margin-top:16px}
button{
  font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.22em;text-transform:uppercase;
  background:var(--pn-phosphor);color:var(--pn-ink-0);border:0;padding:10px 24px;cursor:pointer;
  box-shadow:var(--pn-glow-med);
}
button:hover{background:var(--pn-phosphor-hi)}
a.back{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--pn-grey-2);text-decoration:none}
a.back:hover{color:var(--pn-phosphor);text-shadow:var(--pn-glow)}
#status{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--pn-grey-1);letter-spacing:.15em}
</style>
</head>
<body>
<div class="classification">AT-01 &middot; operator only</div>
<h1>Base Prompt</h1>
<div class="subtitle">operator-controlled framing — agent cannot edit this</div>
<textarea id="prompt">{{CURRENT_PROMPT}}</textarea>
<div class="bar">
  <button onclick="save()">save</button>
  <a class="back" href="/">&larr; back to chat</a>
  <span id="status"></span>
</div>
<script>
function save(){
  const s=document.getElementById('status');
  s.textContent='saving...';
  s.style.color='var(--pn-amber)';
  fetch('/prompt',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:document.getElementById('prompt').value})})
  .then(r=>r.json()).then(j=>{
    if(j.status==='saved'){s.textContent='saved';s.style.color='var(--pn-phosphor)'}
    else{s.textContent=j.error||'error';s.style.color='var(--pn-burn)'}
  }).catch(()=>{s.textContent='error';s.style.color='var(--pn-burn)'});
}
</script>
</body>
</html>
"""
