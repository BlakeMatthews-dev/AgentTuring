"""A2A guest peers — outbound delegation to external A2A agents.

ADR-K8S-029: Stronghold agents can delegate tasks to external A2A peers.
Trust relationships are per-tenant. Cross-tenant delegation forbidden by default.
Every outbound call is audited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger("stronghold.a2a.guest_peers")


@dataclass(frozen=True)
class PeerTrust:
    """Trust relationship with an external A2A peer."""

    peer_url: str
    peer_name: str
    tenant_id: str
    auth_method: str = "api_token"  # "api_token" | "oauth" | "mtls"
    auth_credential: str = ""  # token value or credential ref
    allowed_agents: tuple[str, ...] = ()  # empty = all agents
    active: bool = True


@dataclass
class DelegationResult:
    """Result of an outbound A2A delegation."""

    task_id: str
    peer_name: str
    status: str  # "submitted" | "completed" | "failed" | "rejected"
    result: str | None = None
    error: str | None = None


@runtime_checkable
class AuditLogger(Protocol):
    """Audit log interface for delegation events."""

    async def log_delegation(
        self,
        peer_name: str,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        status: str,
        detail: str,
    ) -> None: ...


class InMemoryAuditLogger:
    """In-memory audit logger for testing."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []

    async def log_delegation(
        self,
        peer_name: str,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        status: str,
        detail: str,
    ) -> None:
        self.entries.append(
            {
                "peer_name": peer_name,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": status,
                "detail": detail,
            }
        )


class GuestPeerRegistry:
    """Registry of trusted external A2A peers, scoped per tenant."""

    def __init__(self, audit: AuditLogger | None = None) -> None:
        self._peers: dict[str, PeerTrust] = {}  # key: "{tenant_id}:{peer_name}"
        self._audit = audit or InMemoryAuditLogger()

    def register_peer(self, peer: PeerTrust) -> None:
        key = f"{peer.tenant_id}:{peer.peer_name}"
        self._peers[key] = peer

    def remove_peer(self, tenant_id: str, peer_name: str) -> bool:
        key = f"{tenant_id}:{peer_name}"
        return self._peers.pop(key, None) is not None

    def get_peer(self, tenant_id: str, peer_name: str) -> PeerTrust | None:
        key = f"{tenant_id}:{peer_name}"
        return self._peers.get(key)

    def list_peers(self, tenant_id: str) -> list[PeerTrust]:
        prefix = f"{tenant_id}:"
        return [p for k, p in self._peers.items() if k.startswith(prefix) and p.active]

    async def delegate(
        self,
        tenant_id: str,
        peer_name: str,
        agent_id: str,
        messages: list[dict[str, str]],
        user_id: str = "",
    ) -> DelegationResult:
        """Delegate a task to an external A2A peer."""
        peer = self.get_peer(tenant_id, peer_name)
        if not peer:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                tenant_id,
                user_id,
                "rejected",
                "peer not found",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error="peer not found",
            )

        if not peer.active:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                tenant_id,
                user_id,
                "rejected",
                "peer inactive",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error="peer inactive",
            )

        if peer.allowed_agents and agent_id not in peer.allowed_agents:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                tenant_id,
                user_id,
                "rejected",
                f"agent '{agent_id}' not in allowed list",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=f"agent '{agent_id}' not allowed on this peer",
            )

        # Build auth headers
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if peer.auth_method == "api_token" and peer.auth_credential:
            headers["Authorization"] = f"Bearer {peer.auth_credential}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{peer.peer_url.rstrip('/')}/a2a/tasks/create",
                    json={"agent_id": agent_id, "messages": messages},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            await self._audit.log_delegation(
                peer_name,
                agent_id,
                tenant_id,
                user_id,
                "submitted",
                f"task_id={data.get('task_id', '')}",
            )
            return DelegationResult(
                task_id=data.get("task_id", ""),
                peer_name=peer_name,
                status="submitted",
            )
        except Exception as exc:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                tenant_id,
                user_id,
                "failed",
                str(exc),
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="failed",
                error=str(exc),
            )
