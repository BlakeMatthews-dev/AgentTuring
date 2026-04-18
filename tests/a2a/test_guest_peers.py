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
    audit = InMemoryAuditLogger()
    reg = GuestPeerRegistry(audit=audit)
    reg.register_peer(_peer())
    # This will fail because the URL is unreachable
    result = await reg.delegate(
        "acme", "ext-peer", "ranger",
        [{"role": "user", "content": "hi"}], user_id="alice",
    )
    assert result.status == "failed"
    assert result.error is not None
    assert len(audit.entries) == 1
    assert audit.entries[0]["status"] == "failed"
    assert audit.entries[0]["user_id"] == "alice"


async def test_audit_logger_protocol() -> None:
    """InMemoryAuditLogger implements the AuditLogger protocol AND actually
    records entries passed to log_delegation — runtime Protocol acceptance
    alone wouldn't catch a method whose implementation is a no-op."""
    from stronghold.a2a.guest_peers import AuditLogger  # noqa: F401 — protocol reference
    audit = InMemoryAuditLogger()
    # Structural contract: the required method is callable on the fake.
    assert callable(getattr(audit, "log_delegation", None))
    # Behavioral: log_delegation actually records an entry we can read back.
    assert audit.entries == []
    await audit.log_delegation(
        peer_name="peer-1",
        agent_id="ranger",
        tenant_id="acme",
        user_id="alice",
        status="ok",
        detail="",
    )
    assert len(audit.entries) == 1
    assert audit.entries[0]["peer_name"] == "peer-1"
    assert audit.entries[0]["status"] == "ok"
    assert audit.entries[0]["tenant_id"] == "acme"


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
