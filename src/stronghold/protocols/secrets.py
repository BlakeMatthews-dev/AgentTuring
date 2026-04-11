"""Secrets backend protocol — abstraction over K8s, Vault, and env-var providers.

A `SecretBackend` is the load-bearing seam between Stronghold's config layer
and whichever store actually holds sensitive material at runtime. The protocol
itself is intentionally tiny: resolve a reference, watch for rotations, close.

Reference syntax (per ADR-K8S-003 and the operator notes on issue #61):

    ${secret:k8s/<namespace>/<secret-name>/<key>}
    ${secret:vault/<mount>/<path>/<key>}
    ${secret:env/<VAR_NAME>}

The first segment after `secret:` is the backend tag and selects which
implementation handles the lookup. Backends are registered with the DI
container; callers never import a concrete backend directly.

All access is policy-gated. Implementations MUST treat `PermissionError` as
the canonical signal that the Cedar PDP (issue #700) denied a tenant-scoped
read; callers can rely on it to distinguish "secret missing" from "you may
not see this secret".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True)
class SecretResult:
    """A resolved secret value plus the version stamp the backend reported.

    The `version` field is optional because the `env` backend has no concept
    of versioning. K8s Secrets surface their `resourceVersion`. Vault returns
    its sequence number. Watchers compare versions to decide whether a
    re-yield is a real change or just a noisy notification.
    """

    value: str
    version: str | None = None


@runtime_checkable
class SecretBackend(Protocol):
    """Resolve and watch secret references from a backing store.

    Implementations are expected to be safe to call concurrently. The
    contract intentionally does NOT promise caching — that is the caller's
    responsibility (typically the config loader, which memoizes resolved
    values for the lifetime of a request).
    """

    async def get_secret(self, ref: str) -> SecretResult:
        """Resolve a secret reference to its current value.

        Args:
            ref: A backend-specific reference such as
                ``"k8s/stronghold-platform/litellm/api-key"``. The leading
                ``${secret:...}`` wrapper has already been stripped by the
                caller; implementations receive the inner path only.

        Returns:
            A `SecretResult` with the current value and (when available) a
            backend version stamp.

        Raises:
            ValueError: The reference syntax is malformed for this backend.
            LookupError: The reference is well-formed but the secret or key
                does not exist in the store.
            PermissionError: The Cedar PDP (issue #700) denied this principal
                read access. Callers MUST NOT confuse this with `LookupError`
                — leaking the difference is a tenant-isolation bug.
        """
        ...

    def watch_changes(self, ref: str) -> AsyncIterator[SecretResult]:
        """Yield a fresh `SecretResult` every time the backing secret changes.

        Implementations are async generators (``async def`` + ``yield``).
        The first value yielded SHOULD be the current state so callers can
        treat the iterator as an authoritative source without an extra
        ``get_secret`` call.

        Args:
            ref: Same shape as `get_secret`.

        Raises:
            ValueError: The reference syntax is malformed.
            LookupError: The secret does not exist.
            PermissionError: Cedar denied access (issue #700).
        """
        ...

    async def close(self) -> None:
        """Release any background watchers, sockets, or pooled connections.

        Idempotent. Safe to call multiple times. After `close()`, calls to
        `get_secret` and `watch_changes` MAY raise `RuntimeError`.
        """
        ...
