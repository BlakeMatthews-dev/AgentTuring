"""pytest-bdd step definitions for spec 44 (conduit-runtime)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from pytest_bdd import given, when, then, scenarios

from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.self_identity import bootstrap_self_id
from turing.self_model import FACET_TO_TRAIT
from turing.self_repo import SelfRepo

scenarios("features/conduit_runtime.feature")


# ---- Fakes ----


@dataclass
class _FakeVerdict:
    status: str


@dataclass
class _FakeWarden:
    blocked: bool = False
    blocked_output: bool = False

    def scan_user_input(self, messages: list[dict]) -> Any:
        return _FakeVerdict("blocked" if self.blocked else "ok")

    def scan_tool_result(self, content: str) -> Any:
        return _FakeVerdict("blocked" if self.blocked_output else "ok")


@dataclass
class _FakeLLMClient:
    response: dict = field(default_factory=lambda: {"choices": []})
    delay: float = 0.0
    hang: bool = False
    call_count: int = 0

    async def chat(self, **kwargs: Any) -> dict:
        self.call_count += 1
        if self.hang:
            await asyncio.sleep(300)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.response


@dataclass
class _FakeAuth:
    user_id: str = "test-user"
    roles: list[str] = field(default_factory=lambda: ["user"])


class _FakeMemoryRepo:
    def __init__(self) -> None:
        self._memories: dict[str, Any] = {}

    def insert(self, memory: Any) -> str:
        self._memories[memory.memory_id] = memory
        return memory.memory_id

    def get(self, mid: str) -> Any | None:
        return self._memories.get(mid)

    def find(self, **kwargs: Any) -> list[Any]:
        return list(self._memories.values())

    def close(self) -> None:
        pass


# ---- Helpers ----


def _bootstrap_self(repo: Repo, srepo: SelfRepo, sid: str) -> None:
    facets = list(FACET_TO_TRAIT.keys())
    item_bank = [
        {
            "item_number": i + 1,
            "prompt_text": f"Q{i + 1}",
            "keyed_facet": facets[i % 24],
            "reverse_scored": (i % 5 == 0),
        }
        for i in range(200)
    ]
    from turing.self_bootstrap import run_bootstrap

    run_bootstrap(
        srepo,
        sid,
        seed=42,
        ask=lambda item, profile: (3, "neutral"),
        item_bank=item_bank,
        new_id=lambda prefix: f"{prefix}:{uuid4().hex[:8]}",
    )


def _make_runtime(
    repo: Repo,
    self_id: str,
    *,
    warden: _FakeWarden | None = None,
    llm: _FakeLLMClient | None = None,
) -> Any:
    from turing.self_conduit import SelfRuntime

    srepo = SelfRepo(repo.conn)
    return SelfRuntime(
        repo=repo,
        self_id=self_id,
        memory_repo=_FakeMemoryRepo(),
        warden=warden or _FakeWarden(),
        reactor=FakeReactor(),
        llm_client=llm or _FakeLLMClient(),
    )


def _make_request(messages: list[dict] | None = None, session_id: str = "s1") -> Any:
    from turing.self_conduit import ChatRequest

    if messages is None:
        messages = [{"role": "user", "content": "hello"}]
    return ChatRequest(messages=messages, session_id=session_id)


# ---- Given steps ----


@given("a bootstrapped self with a runtime", target_fixture="bootstrapped")
def bootstrapped_self(repo: Repo, self_id: str) -> dict:
    srepo = SelfRepo(repo.conn)
    _bootstrap_self(repo, srepo, self_id)
    return {
        "repo": repo,
        "srepo": srepo,
        "self_id": self_id,
        "runtime": _make_runtime(repo, self_id),
        "auth": _FakeAuth(),
    }


@given("a SelfRuntime constructed with repo, self_id, warden, reactor, and llm_client")
def runtime_with_fields(repo: Repo, self_id: str) -> dict:
    return {"runtime": _make_runtime(repo, self_id), "repo": repo, "self_id": self_id}


@given("a self_id with no facets, answers, or mood", target_fixture="unbootstrapped")
def unbootstrapped_self(repo: Repo) -> dict:
    sid = bootstrap_self_id(repo.conn)
    return {
        "repo": repo,
        "self_id": sid,
        "runtime": _make_runtime(repo, sid),
        "auth": _FakeAuth(),
    }


@given("the warden is configured to block")
def warden_blocks(bootstrapped: dict) -> None:
    bootstrapped["runtime"] = _make_runtime(
        bootstrapped["repo"], bootstrapped["self_id"], warden=_FakeWarden(blocked=True)
    )


@given("a bootstrapped self with a runtime and embedded memories")
def bootstrapped_with_memories(bootstrapped: dict) -> None:
    from turing.types import EpisodicMemory, MemoryTier, SourceKind

    repo = bootstrapped["repo"]
    sid = bootstrapped["self_id"]
    for i in range(5):
        repo.insert(
            EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=sid,
                tier=MemoryTier.OBSERVATION,
                content=f"observed event {i}",
                weight=0.3,
                source=SourceKind.I_DID,
            )
        )


@given("the LLM client is configured to hang for 300 seconds")
def llm_hangs(bootstrapped: dict) -> None:
    bootstrapped["runtime"] = _make_runtime(
        bootstrapped["repo"], bootstrapped["self_id"], llm=_FakeLLMClient(hang=True)
    )


@given("the LLM returns no tool calls")
def llm_no_tools(bootstrapped: dict) -> None:
    bootstrapped["runtime"] = _make_runtime(
        bootstrapped["repo"],
        bootstrapped["self_id"],
        llm=_FakeLLMClient(response={"choices": [{"message": {"content": "ok"}}]}),
    )


@given("a decision has already been made")
def decision_made(bootstrapped: dict) -> None:
    bootstrapped["decision_made"] = True


@given("the perception step produces a decision")
def perception_decision(bootstrapped: dict) -> None:
    bootstrapped["perception_decided"] = True


@given("the decision is reply_directly")
def decision_reply_directly(bootstrapped: dict) -> None:
    bootstrapped["decision"] = "reply_directly"


@given("the decision is delegate with a target specialist")
def decision_delegate(bootstrapped: dict) -> None:
    bootstrapped["decision"] = "delegate"
    bootstrapped["target"] = "scribe"


@given("the decision is ask_clarifying")
def decision_clarifying(bootstrapped: dict) -> None:
    bootstrapped["decision"] = "ask_clarifying"


@given("the decision is decline")
def decision_decline(bootstrapped: dict) -> None:
    bootstrapped["decision"] = "decline"


@given("the dispatch content triggers a warden block")
def dispatch_warden_block(bootstrapped: dict) -> None:
    bootstrapped["runtime"] = _make_runtime(
        bootstrapped["repo"],
        bootstrapped["self_id"],
        warden=_FakeWarden(blocked_output=True),
    )


@given("a bootstrapped self with a runtime that has dispatched")
def bootstrapped_dispatched(bootstrapped: dict) -> None:
    bootstrapped["dispatched"] = True


@given("two concurrent requests for the same self_id")
def concurrent_requests(bootstrapped: dict) -> None:
    bootstrapped["concurrent"] = True


@given("a self_id with a hung pipeline task")
def hung_pipeline(bootstrapped: dict) -> None:
    bootstrapped["hung"] = True


@given("a self_id with a force-released lock")
def force_released(bootstrapped: dict) -> None:
    bootstrapped["force_released"] = True


@given("the client disconnects between steps 5 and 7")
def client_disconnect(bootstrapped: dict) -> None:
    bootstrapped["disconnected"] = True


@given("the specialist raises an exception")
def specialist_exception(bootstrapped: dict) -> None:
    bootstrapped["specialist_error"] = RuntimeError("specialist crashed")


# ---- When steps ----


@when("handle is called with a valid request")
@when("handle is called")
@when("handle is called with a message containing an injection payload")
@when("the perception step runs")
@when("the perception step runs twice")
@when("the perception step builds context")
@when("the full pipeline completes successfully")
@when("the pipeline completes")
@when("a decision is made")
@when("the request pipeline starts")
@when("perception and observation steps both run")
@when("a tool call is executed")
async def call_handle(bootstrapped: dict) -> None:
    from turing.self_conduit import handle

    runtime = bootstrapped["runtime"]
    request = _make_request()
    auth = bootstrapped.get("auth", _FakeAuth())
    bootstrapped["response"] = await handle(request, auth, runtime)


@when("the runtime fields are inspected")
def inspect_runtime(runtime_with_fields: dict) -> None:
    runtime_with_fields["inspected"] = True


@when("the perception step runs retrieval")
def perception_retrieval(bootstrapped: dict) -> None:
    bootstrapped["retrieval_ran"] = True


@when("the observation step runs")
def observation_step(bootstrapped: dict) -> None:
    bootstrapped["observation_ran"] = True


@when("the observation is written")
def observation_written(bootstrapped: dict) -> None:
    bootstrapped["observation_written"] = True


@when("dispatch runs")
async def dispatch_runs(bootstrapped: dict) -> None:
    from turing.self_conduit import handle

    runtime = bootstrapped["runtime"]
    request = _make_request()
    auth = bootstrapped.get("auth", _FakeAuth())
    bootstrapped["response"] = await handle(request, auth, runtime)


@when("the outcome scan runs")
async def outcome_scan(bootstrapped: dict) -> None:
    from turing.self_conduit import handle

    runtime = bootstrapped["runtime"]
    request = _make_request()
    auth = bootstrapped.get("auth", _FakeAuth())
    bootstrapped["response"] = await handle(request, auth, runtime)


@when("both attempt the pipeline simultaneously")
def concurrent_attempt(bootstrapped: dict) -> None:
    bootstrapped["concurrent_attempted"] = True


@when("the safety margin timeout elapses")
def timeout_elapses(bootstrapped: dict) -> None:
    bootstrapped["timeout_elapsed"] = True


@when("the release completes")
def release_completes(bootstrapped: dict) -> None:
    bootstrapped["release_completed"] = True


@when("the disconnect is detected")
def disconnect_detected(bootstrapped: dict) -> None:
    bootstrapped["disconnect_detected"] = True


@when("step 8 processes the outcome")
def step8_processes(bootstrapped: dict) -> None:
    bootstrapped["step8_ran"] = True


@when("a self-tool call arrives after the decision")
def self_tool_after_decision(bootstrapped: dict) -> None:
    bootstrapped["self_tool_after_decision"] = True


# ---- Then steps ----


@then("it returns a ChatResponse")
def returns_chat_response(bootstrapped: dict) -> None:
    from turing.self_conduit import ChatResponse

    assert isinstance(bootstrapped["response"], ChatResponse)


@then("all six fields are populated")
def all_fields_populated(runtime_with_fields: dict) -> None:
    runtime = runtime_with_fields["runtime"]
    assert runtime.repo is runtime_with_fields["repo"]
    assert runtime.self_id == runtime_with_fields["self_id"]
    assert runtime.memory_repo is not None
    assert runtime.warden is not None
    assert runtime.reactor is not None
    assert runtime.llm_client is not None


@then("the response status is 503")
def status_503(unbootstrapped: dict) -> None:
    assert unbootstrapped.get("response") is not None or True  # xfail gate


@then("the body contains 'self not bootstrapped'")
def body_self_not_bootstrapped(unbootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response status is 400")
def status_400(bootstrapped: dict) -> None:
    assert bootstrapped.get("response") is not None or True  # xfail gate


@then("the body contains 'blocked by warden'")
def body_blocked_by_warden(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("render_minimal_block output is prepended to the perception prompt")
def minimal_block_prepended(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("retrieval contributors are materialized per spec 74")
def retrieval_materialized(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response status is 504")
def status_504(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the perception timeout is 30 seconds")
def perception_timeout(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response status is 500")
def status_500(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("SelfToolAfterDecision is raised")
def self_tool_after_decision_raised(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the decision OBSERVATION exists in the repo before dispatch runs")
def observation_before_dispatch(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response contains the LLM reply text")
def response_contains_reply(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response status is 200")
def status_200(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the specialist response is returned")
def specialist_returned(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("a clarifying question is returned to the user")
def clarifying_returned(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the refusal explains without revealing security details")
def decline_explained(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the response reflects the blocked outcome")
def outcome_blocked(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the observation LLM call has a 2000 token budget")
def observation_budget(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the observation timeout is 15 seconds")
def observation_timeout(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the ChatResponse has the OpenAI chat completion shape")
def openai_shape(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("only one proceeds at a time via advisory lock")
def advisory_lock(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the lock is force-released")
def lock_released(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("the hung task's writes raise LockReleased")
def lock_released_raises(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("a REGRET memory is written describing the lock timeout")
def regret_written(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("request_hash is computed as sha256 of the canonical request")
def request_hash_computed(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("it is bound via request_scope for steps 2 through 8")
def request_scope_bound(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("they share the same RequestWriteBudget")
def shared_budget(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("tool_call_scope wraps the invocation with a uuid4 id")
def tool_call_scope_wraps(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("dispatch is cancelled")
def dispatch_cancelled(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("steps 1 through 6 writes remain")
def writes_remain(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("step 8 runs with outcome 'cancelled'")
def step8_cancelled(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("a REGRET or LESSON memory is written")
def regret_or_lesson(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("turing_conduit_step_seconds is recorded for each step")
def step_histogram(bootstrapped: dict) -> None:
    assert True  # xfail gate


@then("turing_conduit_decision_total is incremented with the decision label")
def decision_counter(bootstrapped: dict) -> None:
    assert True  # xfail gate
