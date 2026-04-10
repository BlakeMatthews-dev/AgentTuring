"""Tests for AKS Helm values overlay."""

from __future__ import annotations

from pathlib import Path

import yaml


def _load_values(name: str) -> dict:
    path = Path("deploy/helm/stronghold") / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text())


def test_aks_values_exist() -> None:
    path = Path("deploy/helm/stronghold/values-aks.yaml")
    assert path.exists(), "values-aks.yaml missing"


def test_aks_openshift_disabled() -> None:
    vals = _load_values("values-aks.yaml")
    assert vals["openshift"]["enabled"] is False


def test_aks_ingress_enabled() -> None:
    vals = _load_values("values-aks.yaml")
    assert vals["ingress"]["enabled"] is True
    assert vals["ingress"]["className"] == "azure-application-gateway"


def test_aks_entra_id_enabled() -> None:
    vals = _load_values("values-aks.yaml")
    assert vals["auth"]["entraId"]["enabled"] is True
    assert vals["auth"]["entraId"]["roleClaim"] == "roles"


def test_aks_vault_azure_auth() -> None:
    vals = _load_values("values-aks.yaml")
    assert vals["vault"]["enabled"] is True
    assert vals["vault"]["authMethod"] == "azure"


def test_aks_storage_class() -> None:
    vals = _load_values("values-aks.yaml")
    sc = vals["postgresql"]["primary"]["persistence"]["storageClassName"]
    assert sc == "managed-csi"


def test_aks_platform_env() -> None:
    vals = _load_values("values-aks.yaml")
    assert vals["env"]["STRONGHOLD_PLATFORM"] == "aks"


def test_main_values_has_vault_config() -> None:
    vals = _load_values("values.yaml")
    assert "vault" in vals
    assert "authMethod" in vals["vault"]
    assert vals["vault"]["authMethod"] == "kubernetes"


def test_main_values_has_secrets_backend() -> None:
    vals = _load_values("values.yaml")
    assert "secretsBackend" in vals
    assert vals["secretsBackend"] == "k8s"


def test_entra_id_has_role_claim() -> None:
    vals = _load_values("values.yaml")
    assert "roleClaim" in vals["auth"]["entraId"]
    assert vals["auth"]["entraId"]["roleClaim"] == "roles"
