"""Tests for Vault Helm template rendering."""

from __future__ import annotations

from pathlib import Path


def test_vault_template_exists() -> None:
    path = Path("deploy/helm/stronghold/templates/vault-deployment.yaml")
    assert path.exists()


def test_vault_template_conditional() -> None:
    """Vault template only renders when vault.enabled is true."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "{{- if .Values.vault.enabled }}" in content
    assert "{{- end }}" in content


def test_vault_template_namespace_configurable() -> None:
    """Vault namespace is not hardcoded."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert '.Values.vault.namespace | default "stronghold-system"' in content


def test_vault_template_uses_openbao_image() -> None:
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "openbao/openbao" in content


def test_vault_template_nonroot() -> None:
    """Vault pod runs as non-root."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "runAsNonRoot: true" in content


def test_vault_template_ipc_lock() -> None:
    """Vault needs IPC_LOCK capability for mlock."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "IPC_LOCK" in content


def test_vault_template_network_policy() -> None:
    """Vault has NetworkPolicy restricting ingress to stronghold-api only."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "NetworkPolicy" in content
    assert "stronghold-api" in content


def test_vault_template_health_probes() -> None:
    """Vault has readiness and liveness probes."""
    content = Path("deploy/helm/stronghold/templates/vault-deployment.yaml").read_text()
    assert "readinessProbe" in content
    assert "livenessProbe" in content
    assert "/v1/sys/health" in content
