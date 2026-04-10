"""Per-user credential vault — protocol and implementations.

ADR-K8S-018: per-user secret paths in Vault/OpenBao.
Supports HashiCorp Vault and OpenBao (API-compatible fork).

Auth methods:
  - Token: static token (dev/testing)
  - Kubernetes: ServiceAccount JWT → Vault token (production on k8s)
  - Azure: Managed Identity → Vault token (production on AKS)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger("stronghold.persistence.vault_client")

# K8s SA token path (projected into pods by kubelet)
_K8S_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


@runtime_checkable
class VaultClient(Protocol):
    """Per-user credential vault with CRUD operations.

    Compatible with both HashiCorp Vault and OpenBao KV v2.
    """

    async def read_secret(self, path: str) -> dict[str, str]:
        """Read a secret at the given path. Returns empty dict if not found."""
        ...

    async def write_secret(self, path: str, data: dict[str, str]) -> None:
        """Write a secret at the given path (upsert)."""
        ...

    async def list_secrets(self, path: str) -> list[str]:
        """List secret keys under the given path."""
        ...

    async def delete_secret(self, path: str) -> None:
        """Delete a secret at the given path. No-op if not found."""
        ...

    async def provision_user(self, user_id: str) -> None:
        """Create the user's secret path and set initial policy."""
        ...


class VaultKV2Client:
    """VaultClient backed by Vault/OpenBao KV v2 secrets engine.

    User secrets live at: {mount}/data/users/{user_id}/{key}

    Auth methods (selected by auth_method param):
      - "token": use a static token (VAULT_TOKEN env var or token param)
      - "kubernetes": exchange K8s ServiceAccount JWT for a Vault token
      - "azure": exchange Azure Managed Identity token for a Vault token
    """

    def __init__(
        self,
        url: str,
        mount_path: str = "secret",
        auth_method: str = "token",
        token: str = "",
        k8s_role: str = "stronghold-api",
        k8s_auth_path: str = "auth/kubernetes",
        azure_role: str = "stronghold-api",
        azure_auth_path: str = "auth/azure",
        azure_resource: str = "https://management.azure.com/",
        lease_ttl: str = "1h",
    ) -> None:
        self._url = url.rstrip("/")
        self._mount = mount_path
        self._auth_method = auth_method
        self._token = token or os.environ.get("VAULT_TOKEN", "")
        self._k8s_role = k8s_role
        self._k8s_auth_path = k8s_auth_path
        self._azure_role = azure_role
        self._azure_auth_path = azure_auth_path
        self._azure_resource = azure_resource
        self._lease_ttl = lease_ttl
        self._client = httpx.AsyncClient(base_url=self._url, timeout=10.0)

    async def _get_token(self) -> str:
        """Get a valid Vault token using the configured auth method."""
        if self._auth_method == "token":
            return self._token
        if self._auth_method == "kubernetes":
            return await self._k8s_login()
        if self._auth_method == "azure":
            return await self._azure_login()
        raise ValueError(f"Unknown auth method: {self._auth_method}")

    async def _k8s_login(self) -> str:
        """Exchange K8s ServiceAccount JWT for a Vault token."""
        sa_token_path = Path(_K8S_SA_TOKEN_PATH)
        if not sa_token_path.exists():
            raise RuntimeError(
                f"K8s ServiceAccount token not found at {_K8S_SA_TOKEN_PATH}. "
                "Ensure the pod has a projected ServiceAccount token volume."
            )
        sa_token = sa_token_path.read_text().strip()
        resp = await self._client.post(
            f"/v1/{self._k8s_auth_path}/login",
            json={"role": self._k8s_role, "jwt": sa_token},
        )
        resp.raise_for_status()
        return resp.json()["auth"]["client_token"]

    async def _azure_login(self) -> str:
        """Exchange Azure Managed Identity token for a Vault token.

        Requires the pod to have a Managed Identity assigned
        (via Azure Workload Identity or AAD Pod Identity).
        """
        # Get Azure IMDS token
        imds_url = (
            "http://169.254.169.254/metadata/identity/oauth2/token"
            f"?api-version=2018-02-01&resource={self._azure_resource}"
        )
        async with httpx.AsyncClient(timeout=5.0) as imds_client:
            imds_resp = await imds_client.get(
                imds_url, headers={"Metadata": "true"},
            )
            imds_resp.raise_for_status()
            azure_jwt = imds_resp.json()["access_token"]

        # Exchange for Vault token
        resp = await self._client.post(
            f"/v1/{self._azure_auth_path}/login",
            json={
                "role": self._azure_role,
                "jwt": azure_jwt,
            },
        )
        resp.raise_for_status()
        return resp.json()["auth"]["client_token"]

    def _headers(self, token: str) -> dict[str, str]:
        return {"X-Vault-Token": token}

    def _kv_data_url(self, path: str) -> str:
        return f"/v1/{self._mount}/data/{path}"

    def _kv_metadata_url(self, path: str) -> str:
        return f"/v1/{self._mount}/metadata/{path}"

    async def read_secret(self, path: str) -> dict[str, str]:
        token = await self._get_token()
        resp = await self._client.get(
            self._kv_data_url(path), headers=self._headers(token),
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        # KV v2: response.data.data contains the actual secret data
        data = body.get("data", {}).get("data", {})
        return {k: str(v) for k, v in data.items()}

    async def write_secret(self, path: str, data: dict[str, str]) -> None:
        token = await self._get_token()
        resp = await self._client.post(
            self._kv_data_url(path),
            headers=self._headers(token),
            # KV v2: must wrap in {"data": ...}
            json={"data": data},
        )
        resp.raise_for_status()

    async def list_secrets(self, path: str) -> list[str]:
        token = await self._get_token()
        # Vault uses LIST method on the metadata endpoint
        resp = await self._client.request(
            "LIST",
            self._kv_metadata_url(path),
            headers=self._headers(token),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        keys: list[str] = body.get("data", {}).get("keys", [])
        return keys

    async def delete_secret(self, path: str) -> None:
        token = await self._get_token()
        resp = await self._client.delete(
            self._kv_metadata_url(path), headers=self._headers(token),
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    async def provision_user(self, user_id: str) -> None:
        user_path = f"users/{user_id}"
        await self.write_secret(
            f"{user_path}/.provisioned", {"status": "active"},
        )
        logger.info("Provisioned vault path for user %s", user_id)

    async def close(self) -> None:
        await self._client.aclose()
