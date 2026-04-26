"""Self-as-Conduit runtime. See specs/conduit-runtime.md.

Implements the 9-step perception → decision → dispatch → observation pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from .self_budget import RequestWriteBudget, use_budget
from .self_forensics import request_scope, tool_call_scope
from .self_memory_bridge import mirror_observation, mirror_opinion
from .self_model import Mood
from .self_surface import SelfNotReady, _bootstrap_complete, render_minimal_block
from .self_warden_gate import WardenVerdict, SelfWriteBlocked


PERCEPTION_TOKEN_BUDGET: int = 6000
PERCEPTION_OUTPUT_BUDGET: int = 2000
PERCEPTION_TIMEOUT_SEC: float = 30.0
OBSERVATION_TOKEN_BUDGET: int = 2000
OBSERVATION_TIMEOUT_SEC: float = 15.0
LOCK_SAFETY_BUDGET: float = PERCEPTION_TIMEOUT_SEC + OBSERVATION_TIMEOUT_SEC + 10.0


@dataclass
class ChatRequest:
    messages: list[dict[str, str]]
    session_id: str | None = None

    def canonical(self) -> str:
        return json.dumps(
            {"messages": self.messages, "session_id": self.session_id}, sort_keys=True
        )

    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()[:16]


@dataclass
class AuthContext:
    user_id: str
    scopes: list[str] = field(default_factory=list)


@dataclass
class ChatResponse:
    status: int = 200
    body: str = ""
    content: str = ""
    conversation_continue: bool = False


@dataclass
class DispatchOutcome:
    status: str = "ok"
    content: str = ""
    error: str | None = None
    blocked: bool = False
    cancelled: bool = False
    conversation_continue: bool = False

    def has_content(self) -> bool:
        return bool(self.content) and not self.cancelled

    @classmethod
    def make_cancelled(cls) -> DispatchOutcome:
        return cls(status="cancelled", cancelled=True)

    def with_blocked(self, verdict) -> DispatchOutcome:
        return DispatchOutcome(status="blocked", content=self.content, blocked=True)


class PerceptionTimeout(Exception):
    pass


class AmbiguousRouting(Exception):
    pass


class SelfToolAfterDecision(Exception):
    pass


class LockReleased(Exception):
    pass


_DECISION_COUNTS: dict[str, int] = {}


def get_decision_counts() -> dict[str, int]:
    return dict(_DECISION_COUNTS)


def _hash_request(request: ChatRequest) -> str:
    return request.request_hash()


class SelfRuntime:
    def __init__(
        self,
        repo,
        self_id: str,
        *,
        warden=None,
        reactor=None,
        llm_client=None,
        memory_repo=None,
    ):
        self.repo = repo
        self.self_id = self_id
        self.warden = warden
        self.reactor = reactor
        self.llm_client = llm_client
        self.memory_repo = memory_repo
        self._perception_lock = threading.Lock()
        self._lock_holder: str | None = None
        self._decision_made: bool = False

    def acquire_perception_lock(self, timeout: float = LOCK_SAFETY_BUDGET) -> bool:
        acquired = self._perception_lock.acquire(timeout=timeout)
        if acquired:
            self._lock_holder = f"lock-{uuid4().hex[:8]}"
        return acquired

    def release_perception_lock(self) -> None:
        self._lock_holder = None
        self._perception_lock.release()

    def invoke(self, tool_name: str, **kwargs) -> Any:
        if self._decision_made and tool_name not in (
            "reply_directly",
            "delegate",
            "ask_clarifying",
            "decline",
        ):
            raise SelfToolAfterDecision(f"{tool_name} called after decision")
        return None


async def handle(
    request: ChatRequest,
    auth: AuthContext,
    runtime: SelfRuntime,
) -> ChatResponse:
    if not _bootstrap_complete(runtime.repo, runtime.self_id):
        return ChatResponse(status=503, body="self not bootstrapped")

    req_hash = _hash_request(request)

    with request_scope(req_hash), use_budget(RequestWriteBudget.fresh()):
        if runtime.warden is not None:
            combined = " ".join(m.get("content", "") for m in request.messages)
            verdict = runtime.warden(combined)
            if verdict is not None and getattr(verdict, "status", None) == "blocked":
                return ChatResponse(status=400, body="request blocked by warden")

        if not runtime.acquire_perception_lock():
            return ChatResponse(status=503, body="self is busy")

        try:
            block = render_minimal_block(runtime.repo, runtime.self_id)
            runtime._decision_made = False

            decision = await _perceive(runtime, block, request)
            if decision is None:
                return ChatResponse(status=500, body="routing failure")

            _record_decision(runtime, decision, req_hash)

            try:
                outcome = await _dispatch(runtime, decision, request, auth)
            except asyncio.CancelledError:
                outcome = DispatchOutcome.make_cancelled()
                raise
            except Exception as exc:
                outcome = DispatchOutcome(status="error", error=repr(exc))

            if outcome.has_content() and runtime.warden is not None:
                out_verdict = runtime.warden(outcome.content)
                if out_verdict is not None and getattr(out_verdict, "status", None) == "blocked":
                    outcome = outcome.with_blocked(out_verdict)

        finally:
            runtime.release_perception_lock()

        return _render_response(outcome)


async def _perceive(runtime: SelfRuntime, block: str, request: ChatRequest) -> dict | None:
    try:
        if runtime.llm_client is not None:
            result = await asyncio.wait_for(
                runtime.llm_client(block, request),
                timeout=PERCEPTION_TIMEOUT_SEC,
            )
            return result
        return {"decision": "reply_directly", "content": "acknowledged"}
    except asyncio.TimeoutError:
        raise PerceptionTimeout("perception timed out")


async def _dispatch(
    runtime: SelfRuntime,
    decision: dict,
    request: ChatRequest,
    auth: AuthContext,
) -> DispatchOutcome:
    kind = decision.get("decision", "reply_directly")
    _DECISION_COUNTS[kind] = _DECISION_COUNTS.get(kind, 0) + 1

    if kind == "reply_directly":
        return DispatchOutcome(content=decision.get("content", ""))
    elif kind == "ask_clarifying":
        return DispatchOutcome(content=decision.get("question", ""), conversation_continue=True)
    elif kind == "decline":
        mirror_opinion(
            runtime.repo,
            runtime.self_id,
            f"I declined to handle a request: {decision.get('reason', 'unspecified')}",
            "decline",
        )
        return DispatchOutcome(content=f"I'd prefer not to: {decision.get('reason', '')}")
    elif kind == "delegate":
        return DispatchOutcome(content=f"Delegated to {decision.get('specialist', 'unknown')}")
    else:
        return DispatchOutcome(status="error", error=f"unknown decision: {kind}")


def _record_decision(runtime: SelfRuntime, decision: dict, req_hash: str) -> None:
    kind = decision.get("decision", "unknown")
    mirror_observation(
        runtime.repo,
        runtime.self_id,
        f"I chose to {kind} for this request",
        "route request",
        context={"decision": kind, "request_hash": req_hash},
    )
    runtime._decision_made = True


def _render_response(outcome: DispatchOutcome) -> ChatResponse:
    if outcome.cancelled:
        return ChatResponse(status=499, body="cancelled")
    if outcome.status == "error":
        return ChatResponse(status=500, body=outcome.error or "internal error")
    if outcome.blocked:
        return ChatResponse(status=200, content="[response filtered]", conversation_continue=True)
    return ChatResponse(
        status=200, content=outcome.content, conversation_continue=outcome.conversation_continue
    )
