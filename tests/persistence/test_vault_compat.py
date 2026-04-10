"""Tests for VaultKV2Client compatibility with HashiCorp Vault + Azure AKS."""

from __future__ import annotations

from stronghold.persistence.vault_client import VaultClient, VaultKV2Client


def test_protocol_compliance() -> None:
    """VaultKV2Client satisfies VaultClient protocol."""
    client = VaultKV2Client(url="http://vault:8200", auth_method="token", token="test")
    assert isinstance(client, VaultClient)


def test_kv_data_url() -> None:
    """KV v2 data endpoint uses /v1/{mount}/data/{path}."""
    client = VaultKV2Client(url="http://vault:8200", mount_path="secret")
    assert client._kv_data_url("users/alice/github") == "/v1/secret/data/users/alice/github"


def test_kv_metadata_url() -> None:
    """KV v2 metadata endpoint uses /v1/{mount}/metadata/{path}."""
    client = VaultKV2Client(url="http://vault:8200", mount_path="secret")
    assert client._kv_metadata_url("users/alice") == "/v1/secret/metadata/users/alice"


def test_custom_mount_path() -> None:
    """Mount path is configurable (not hardcoded to 'secret')."""
    client = VaultKV2Client(url="http://vault:8200", mount_path="stronghold")
    assert client._kv_data_url("users/alice/key") == "/v1/stronghold/data/users/alice/key"


def test_token_auth_method() -> None:
    """Token auth returns the static token."""
    client = VaultKV2Client(url="http://vault:8200", auth_method="token", token="hvs.test123")
    import asyncio
    token = asyncio.new_event_loop().run_until_complete(client._get_token())
    assert token == "hvs.test123"


def test_token_from_env() -> None:
    """Token auth falls back to VAULT_TOKEN env var."""
    import os
    os.environ["VAULT_TOKEN"] = "hvs.from-env"
    try:
        client = VaultKV2Client(url="http://vault:8200", auth_method="token")
        import asyncio
        token = asyncio.new_event_loop().run_until_complete(client._get_token())
        assert token == "hvs.from-env"
    finally:
        os.environ.pop("VAULT_TOKEN", None)


def test_unknown_auth_method_raises() -> None:
    """Unknown auth method raises ValueError."""
    client = VaultKV2Client(url="http://vault:8200", auth_method="magic")
    import asyncio
    import pytest
    with pytest.raises(ValueError, match="Unknown auth method"):
        asyncio.new_event_loop().run_until_complete(client._get_token())


def test_k8s_auth_configured() -> None:
    """Kubernetes auth stores role and path correctly."""
    client = VaultKV2Client(
        url="http://vault:8200",
        auth_method="kubernetes",
        k8s_role="my-role",
        k8s_auth_path="auth/k8s-cluster-1",
    )
    assert client._k8s_role == "my-role"
    assert client._k8s_auth_path == "auth/k8s-cluster-1"


def test_azure_auth_configured() -> None:
    """Azure auth stores role, path, and resource correctly."""
    client = VaultKV2Client(
        url="http://vault:8200",
        auth_method="azure",
        azure_role="aks-stronghold",
        azure_auth_path="auth/azure-prod",
        azure_resource="https://vault.azure.net",
    )
    assert client._azure_role == "aks-stronghold"
    assert client._azure_auth_path == "auth/azure-prod"
    assert client._azure_resource == "https://vault.azure.net"


def test_headers_format() -> None:
    """Auth header uses X-Vault-Token (compatible with Vault and OpenBao)."""
    client = VaultKV2Client(url="http://vault:8200")
    headers = client._headers("hvs.test")
    assert headers == {"X-Vault-Token": "hvs.test"}
