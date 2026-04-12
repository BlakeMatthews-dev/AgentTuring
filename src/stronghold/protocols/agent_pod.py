"""Agent pod discovery, registration, and spawning protocol.

The per-tenant per-user agent pod model is described in ARCHITECTURE.md §9
and in the operator notes for issue #371. This module defines the seam
between callers (the routing layer, the arbiter, the spawner client) and
the concrete K8s-backed discovery service that lives at
``stronghold.agent_pod.discovery.AgentPodDiscovery``.

Two protocols live here:

- ``AgentPodDiscovery`` — find / register / unregister pods. Issue #373.
- ``AgentPodSpawner`` — extend later in #374 to add ``spawn_user_pod`` and
  cleanup methods. Defined in this file (rather than its own) per the
  operator notes on #774, which call out that the spawner extends the
  same protocol surface so callers don't have to import two modules.

The K8s label selector is the source of truth. Redis is a cache. Pod
identity is ``(tenant_id, user_id, agent_type)``; ``pod_name`` is included
in registration/unregistration calls so the discovery service can detect
generation skew when a pod is recreated under the same identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentPodInfo:
    """Snapshot of a discovered agent pod.

    Returned by ``AgentPodDiscovery.get_user_pod``. ``ip`` is the pod IP
    suitable for direct addressing (Stronghold uses pod IPs from
    discovery, not service-level load balancing). ``generation`` is a
    monotonic counter the discovery service bumps every time a pod is
    re-registered for the same identity, so callers can detect that the
    pod they were addressing has been recreated.
    """

    ip: str
    generation: int
    pod_name: str


@runtime_checkable
class AgentPodDiscovery(Protocol):
    """Discover and track per-tenant per-user agent pods.

    Implementations are expected to be safe to call concurrently. The
    contract intentionally does NOT promise persistence beyond the
    process — the K8s label selector is the source of truth. Caches
    (Redis, in-memory) are the implementation's business.
    """

    async def get_user_pod(
        self,
        tenant_id: str,
        user_id: str,
        agent_type: str,
    ) -> AgentPodInfo | None:
        """Find the pod currently serving this (tenant, user, agent_type).

        Returns ``None`` if no pod is registered. The discovery service
        SHOULD attempt a K8s label query on cache miss before returning
        ``None``, so callers can treat ``None`` as authoritative.

        Args:
            tenant_id: Tenant slug per the namespace naming in
                ADR-K8S-001 (``stronghold-tenant-{slug}``).
            user_id: Stable user identifier.
            agent_type: Agent role (e.g. ``"mason"``, ``"davinci"``).

        Returns:
            ``AgentPodInfo`` if a pod is registered, ``None`` otherwise.

        Raises:
            PermissionError: Cedar PDP (#700) denied tenant-scoped
                discovery — i.e. a caller in tenant A asked about a pod
                in tenant B. Tenant-isolation invariant.
        """
        ...

    async def register_pod(
        self,
        tenant_id: str,
        user_id: str,
        agent_type: str,
        pod_name: str,
        ip: str,
        generation: int,
    ) -> None:
        """Record a freshly-spawned pod in the discovery service.

        Idempotent within a single ``generation``. Re-registering the
        same identity with a *higher* generation replaces the prior
        entry; a *lower* generation is a no-op so out-of-order callbacks
        from the spawner can't roll back the live mapping.

        Raises:
            PermissionError: Cedar denied write access for this tenant.
        """
        ...

    async def unregister_pod(
        self,
        tenant_id: str,
        user_id: str,
        agent_type: str,
        pod_name: str,
    ) -> None:
        """Drop the discovery entry for this pod.

        ``pod_name`` is required so the watcher's pod-deletion callback
        can avoid evicting an entry that has already been replaced by a
        re-registration with the same identity but a different pod_name.

        Raises:
            PermissionError: Cedar denied write access for this tenant.
        """
        ...

    async def close(self) -> None:
        """Release any background watchers, sockets, or pooled connections.

        Idempotent. Safe to call multiple times.
        """
        ...
