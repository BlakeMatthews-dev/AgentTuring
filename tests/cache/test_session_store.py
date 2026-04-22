"""Tests for RedisSessionStore using fakeredis."""

from __future__ import annotations

import json
import time

import fakeredis.aioredis
import pytest

from stronghold.cache.session_store import RedisSessionStore


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def store(redis_client):
    return RedisSessionStore(redis=redis_client, ttl_seconds=3600, max_messages=10)


# ---- get_history ----

async def test_get_history_empty(store):
    result = await store.get_history("org/team/user:sess1")
    assert result == []


async def test_get_history_rejects_bare_session_id(store):
    """Bare session IDs (not org-scoped) raise ValueError."""
    with pytest.raises(ValueError, match="org-scoped"):
        await store.get_history("bare-session-id")


async def test_get_history_returns_messages(store):
    await store.append_messages("org/team/user:s1", [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ])
    history = await store.get_history("org/team/user:s1")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "hello"}
    assert history[1] == {"role": "assistant", "content": "hi"}


async def test_get_history_filters_expired_messages(redis_client):
    """Messages older than the TTL are filtered out on read."""
    store = RedisSessionStore(redis=redis_client, ttl_seconds=5, max_messages=100)
    # Manually insert an old message
    key = "stronghold:session:org/team/user:s2"
    old_entry = json.dumps({"role": "user", "content": "old", "_ts": time.time() - 100})
    new_entry = json.dumps({"role": "user", "content": "new", "_ts": time.time()})
    await redis_client.rpush(key, old_entry, new_entry)

    history = await store.get_history("org/team/user:s2")
    assert len(history) == 1
    assert history[0]["content"] == "new"


async def test_get_history_respects_max_messages(store):
    """Only the most recent N messages are returned."""
    msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(15)]
    await store.append_messages("org/team/user:s3", msgs)
    history = await store.get_history("org/team/user:s3", max_messages=5)
    assert len(history) == 5
    assert history[-1]["content"] == "msg-14"


async def test_get_history_refreshes_ttl(store, redis_client):
    """Accessing history refreshes the key TTL."""
    await store.append_messages("org/team/user:s4", [
        {"role": "user", "content": "test"},
    ])
    await store.get_history("org/team/user:s4")
    ttl = await redis_client.ttl("stronghold:session:org/team/user:s4")
    assert ttl > 0


# ---- append_messages ----

async def test_append_rejects_bare_session_id(store, redis_client):
    with pytest.raises(ValueError, match="org-scoped"):
        await store.append_messages("bare-id", [{"role": "user", "content": "x"}])


async def test_append_empty_messages_noop(store, redis_client):
    await store.append_messages("org/team/user:s5", [])
    keys = await redis_client.keys("stronghold:session:*")
    assert len(keys) == 0


async def test_append_filters_invalid_roles(store):
    """Only user and assistant roles are stored."""
    await store.append_messages("org/team/user:s6", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "hi"},
    ])
    history = await store.get_history("org/team/user:s6")
    assert len(history) == 2
    assert history[0]["content"] == "hello"
    assert history[1]["content"] == "hi"


async def test_append_filters_non_string_content(store):
    """Non-string content messages are skipped."""
    await store.append_messages("org/team/user:s7", [
        {"role": "user", "content": ["not", "a", "string"]},
        {"role": "user", "content": "valid"},
    ])
    history = await store.get_history("org/team/user:s7")
    assert len(history) == 1
    assert history[0]["content"] == "valid"


async def test_append_trims_to_max(store, redis_client):
    """List is trimmed to max_messages after append."""
    for i in range(20):
        await store.append_messages("org/team/user:s8", [
            {"role": "user", "content": f"msg-{i}"},
        ])
    key = "stronghold:session:org/team/user:s8"
    length = await redis_client.llen(key)
    assert length <= 10


# ---- delete_session ----

async def test_delete_session(store, redis_client):
    await store.append_messages("org/team/user:s9", [
        {"role": "user", "content": "hello"},
    ])
    await store.delete_session("org/team/user:s9")
    history = await store.get_history("org/team/user:s9")
    assert history == []


async def test_delete_session_rejects_bare_id(store, redis_client):
    """Bare session ID delete raises ValueError."""
    with pytest.raises(ValueError, match="org-scoped"):
        await store.delete_session("bare-id")
