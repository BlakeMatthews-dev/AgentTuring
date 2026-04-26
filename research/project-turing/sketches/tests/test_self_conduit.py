"""Tests for turing.self_conduit — AC-44.1..12."""

from __future__ import annotations

import pytest

from turing.self_conduit import (
    AuthContext,
    ChatRequest,
    ChatResponse,
    DispatchOutcome,
    SelfRuntime,
    SelfToolAfterDecision,
    get_decision_counts,
    handle,
)


class _DualRepo:
    def __init__(self, repo, srepo):
        self._repo = repo
        self._srepo = srepo

    def __getattr__(self, name):
        try:
            return getattr(self._srepo, name)
        except AttributeError:
            return getattr(self._repo, name)


def test_request_hash_16_hex_deterministic():
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], session_id="s1")
    h = req.request_hash()
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)
    assert req.request_hash() == h


def test_self_runtime_stores_repo_and_self_id(repo, srepo, self_id):
    rt = SelfRuntime(repo=srepo, self_id=self_id)
    assert rt.repo is srepo
    assert rt.self_id is self_id


def test_perception_lock_acquire_release(repo, srepo, self_id):
    rt = SelfRuntime(repo=srepo, self_id=self_id)
    assert rt.acquire_perception_lock(timeout=1) is True
    rt.release_perception_lock()


def test_invoke_after_decision_raises(repo, srepo, self_id):
    rt = SelfRuntime(repo=srepo, self_id=self_id)
    rt._decision_made = True
    with pytest.raises(SelfToolAfterDecision):
        rt.invoke("some_tool")


def test_dispatch_outcome_cancelled():
    o = DispatchOutcome.make_cancelled()
    assert o.cancelled is True
    assert o.has_content() is False


def test_dispatch_outcome_with_blocked():
    o = DispatchOutcome(content="hello")
    blocked = o.with_blocked("verdict")
    assert blocked.blocked is True


def test_get_decision_counts_returns_dict():
    result = get_decision_counts()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_handle_unbootstrapped_returns_503(repo, srepo, self_id):
    rt = SelfRuntime(repo=srepo, self_id=self_id)
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], session_id="s1")
    auth = AuthContext(user_id="u1")
    resp = await handle(req, auth, rt)
    assert resp.status == 503


@pytest.mark.asyncio
async def test_handle_bootstrapped_default_reply_200(repo, srepo, bootstrapped_id):
    dual = _DualRepo(repo, srepo)
    rt = SelfRuntime(repo=dual, self_id=bootstrapped_id)
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], session_id="s1")
    auth = AuthContext(user_id="u1")
    resp = await handle(req, auth, rt)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_handle_warden_blocks_returns_400(repo, srepo, bootstrapped_id):
    warden = lambda text: type("V", (), {"status": "blocked"})()
    rt = SelfRuntime(repo=srepo, self_id=bootstrapped_id, warden=warden)
    req = ChatRequest(messages=[{"role": "user", "content": "hi"}], session_id="s1")
    auth = AuthContext(user_id="u1")
    resp = await handle(req, auth, rt)
    assert resp.status == 400
