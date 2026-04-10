"""Tests for A2A guest peers (ADR-K8S-029)."""

from __future__ import annotations

from stronghold.a2a.guest_peers import (
    DelegationResult,
    GuestPeerRegistry,
    InMemoryAuditLogger,
    PeerTrust,
)


def _peer(name: str = "ext-peer", tenant_id: str = "acme", **kw: object) -> PeerTrust:
    return PeerTrust(
        peer_url="http://external-peer:8100",
        peer_name=name,
        tenant_id=tenant_id,
        auth_method="api_token",
        auth_credential="sk-external",
        **kw,  # type: ignore[arg-type]
    )


def test_register_and_get_peer() -> None:
    reg = GuestPeerRegistry()
    reg.register_peer(_peer())
    peer = reg.get_peer("acme", "ext-peer")
    assert peer is not None
    assert peer.peer_name == "ext-peer"


def test_get_peer_wrong_tenant() -> None:
    reg = GuestPeerRegistry()
    reg.register_peer(_peer(tenant_id="acme"))
    assert reg.get_peer("evil-corp", "ext-peer") is None


def test_remove_peer() -> None:
    reg = GuestPeerRegistry()
    reg.register_peer(_peer())
    assert reg.remove_peer("acme", "ext-peer") is True
    assert reg.get_peer("acme", "ext-peer") is None


def test_remove_nonexistent() -> None:
    reg = GuestPeerRegistry()
    assert reg.remove_peer("acme", "nope") is False


def test_list_peers() -> None:
    reg = GuestPeerRegistry()
    reg.register_peer(_peer("peer-1", "acme"))
    reg.register_peer(_peer("peer-2", "acme"))
    reg.register_peer(_peer("peer-3", "other"))
    peers = reg.list_peers("acme")
    assert len(peers) == 2
    names = {p.peer_name for p in peers}
    assert names == {"peer-1", "peer-2"}


def test_list_peers_excludes_inactive() -> None:
    reg = GuestPeerRegistry()
    reg.register_peer(_peer("active", "acme"))
    reg.register_peer(_peer("inactive", "acme", active=False))
    peers = reg.list_peers("acme")
    assert len(peers) == 1
    assert peers[0].peer_name == "active"


async def test_delegate_peer_not_found() -> None:
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    result = await reg.delegate("acme", "nonexistent", "ranger", [{"role": "user", "content": "hi"}])
    assert result.status == "rejected"
    assert "not found" in (result.error or "")
    assert len(audit.entries) == 1
    assert audit.entries[0]["status"] == "rejected"


async def test_delegate_inactive_peer() -> None:
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer(active=False))
    result = await reg.delegate("acme", "ext-peer", "ranger", [{"role": "user", "content": "hi"}])
    assert result.status == "rejected"
    assert "inactive" in (result.error or "")


async def test_delegate_agent_not_allowed() -> None:
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer(allowed_agents=("ranger",)))
    result = await reg.delegate("acme", "ext-peer", "forge", [{"role": "user", "content": "hi"}])
    assert result.status == "rejected"
    assert "not allowed" in (result.error or "")


async def test_delegate_network_failure() -> None:
    """Use respx to deterministically simulate network failure (not dep on unreachable host)."""
    import respx
    import httpx

    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer())
    with respx.mock:
        respx.post("http://external-peer:8100/a2a/tasks/create").mock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        result = await reg.delegate(
            "acme", "ext-peer", "ranger",
            [{"role": "user", "content": "hi"}], user_id="alice",
        )
    assert result.status == "failed"
    assert result.error is not None
    assert "connection refused" in result.error
    assert len(audit.entries) == 1
    assert audit.entries[0]["status"] == "failed"
    assert audit.entries[0]["user_id"] == "alice"


async def test_delegate_success_sends_correct_payload() -> None:
    """Real HTTP layer: verify auth header, URL, and payload shape."""
    import respx
    import httpx
    import json as _json

    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer())

    with respx.mock:
        route = respx.post("http://external-peer:8100/a2a/tasks/create").mock(
            return_value=httpx.Response(201, json={"task_id": "t-xyz", "status": "submitted"}),
        )
        result = await reg.delegate(
            "acme", "ext-peer", "ranger",
            [{"role": "user", "content": "hello"}], user_id="alice",
        )

    assert result.status == "submitted"
    assert result.task_id == "t-xyz"
    assert route.called
    req = route.calls.last.request
    # Auth header with token
    assert req.headers["authorization"] == "Bearer sk-external"
    # Payload shape
    body = _json.loads(req.content)
    assert body["agent_id"] == "ranger"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    # Audit
    assert audit.entries[-1]["status"] == "submitted"


async def test_delegate_http_error_recorded() -> None:
    """HTTP 500 from peer should be recorded as failed, not submitted."""
    import respx
    import httpx

    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer())

    with respx.mock:
        respx.post("http://external-peer:8100/a2a/tasks/create").mock(
            return_value=httpx.Response(500, text="internal error"),
        )
        result = await reg.delegate(
            "acme", "ext-peer", "ranger",
            [{"role": "user", "content": "hi"}], user_id="alice",
        )

    assert result.status == "failed"
    assert audit.entries[-1]["status"] == "failed"


def test_audit_logger_protocol() -> None:
    from stronghold.a2a.guest_peers import AuditLogger
    audit = InMemoryAuditLogger()
    assert isinstance(audit, AuditLogger)


async def test_delegate_empty_allowed_agents_means_all() -> None:
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer(allowed_agents=()))
    result = await reg.delegate("acme", "ext-peer", "any-agent", [{"role": "user", "content": "hi"}])
    assert result.status == "failed"  # network error, not policy rejection
    assert "not allowed" not in (result.error or "")


async def test_audit_entry_has_all_fields() -> None:
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    await reg.delegate("acme", "missing", "ranger", [{"role": "user", "content": "hi"}], user_id="alice")
    entry = audit.entries[0]
    assert entry["peer_name"] == "missing"
    assert entry["agent_id"] == "ranger"
    assert entry["tenant_id"] == "acme"
    assert entry["user_id"] == "alice"
    assert entry["status"] == "rejected"
