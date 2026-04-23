# Stronghold Vault (OpenBao) Helm Chart

This Helm chart deploys OpenBao (an open-source fork of HashiCorp Vault) for secret management in the Stronghold agent governance platform.

## Features

- **Secret Storage**: Secure storage for agent credentials, API keys, and provider credentials
- **Dynamic Secrets**: Auto-rotation of credentials for databases, cloud providers, etc.
- **Namespace Isolation**: Per-tenant secret isolation using Kubernetes namespaces
- **Authentication Methods**:
  - Kubernetes service account authentication
  - JWT/OIDC authentication (Azure AD integration)
- **Policy Management**: Fine-grained access control for agents and services
- **Audit Logging**: Complete audit trail of all secret access

## Prerequisites

- Kubernetes 1.25+
- Helm 3.0+
- Storage class for persistent volume (default: standard)

## Installation

```bash
# Add the HashiCorp Helm repository
helm repo add hashicorp https://helm.releases.hashicorp.com

# Install Stronghold Vault
helm install stronghold-vault ./helm/vault -n stronghold-platform --create-namespace
```

## Configuration

Key configuration parameters are in `values.yaml`:

### Server Settings
- `server.enabled`: Enable Vault server
- `server.dataStorage.size`: PVC size for Vault data storage (default: 10Gi)
- `server.resources`: CPU/memory requests and limits

### Stronghold Integration
- `stronghold.enabled`: Enable Stronghold-specific integration
- `stronghold.namespaces`: List of namespaces for per-tenant isolation
- `stronghold.policies`: Vault policies for agent and secret access
- `stronghold.authMethods`: Authentication methods (Kubernetes, JWT/OIDC)
- `stronghold.secrets`: Pre-provisioned secrets and credentials

### Authentication Methods

#### Kubernetes Authentication
Allows Kubernetes service accounts to authenticate to Vault:

```yaml
stronghold.authMethods.kubernetes.enabled: true
```

#### JWT/OIDC Authentication
Integration with Azure AD for user authentication:

```yaml
stronghold.authMethods.jwt.enabled: true
stronghold.authMethods.jwt.config.oidc_discovery_url: "https://login.microsoftonline.com/<tenant-id>/v2.0"
stronghold.authMethods.jwt.config.oidc_client_id: "<client-id>"
```

### Secret Structure

Secrets are organized under the `stronghold/` path:

```
stronghold/data/agents/credentials/*    # Agent-specific credentials
stronghold/data/providers/credentials/* # LLM provider API keys
stronghold/data/database/credentials/*   # Database credentials
stronghold/data/storage/credentials/*    # Storage credentials (S3, Azure, etc.)
```

## Usage

### Access Vault UI

```bash
# Port-forward to access Vault UI
kubectl port-forward -n stronghold-platform svc/stronghold-vault 8200:8200

# Open http://localhost:8200/ui
# Login with root token from values.yaml
```

### Initialize Vault

First-time initialization:

```bash
export VAULT_ADDR="http://localhost:8200"
export VAULT_TOKEN="root"

# Initialize and unseal (if not using HA)
vault operator init

# Unseal Vault (if needed)
vault operator unseal
```

### Configure Stronghold Policies

Policies are automatically applied from `values.yaml`. You can also add custom policies:

```bash
vault policy write my-policy - <<EOF
path "stronghold/data/*" {
  capabilities = ["read"]
}
EOF
```

### Configure Auth Methods

Enable Kubernetes authentication:

```bash
vault auth enable kubernetes
vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

Create a role for Stronghold agents:

```bash
vault write auth/kubernetes/role/stronghold-agent \
    bound_service_account_names=stronghold-agent \
    bound_service_account_namespaces=stronghold-platform \
    policies=agent-read,secrets-read \
    ttl=24h
```

### Read Secrets

Using the Stronghold Vault client:

```python
from stronghold.security.vault_client import VaultClient

client = VaultClient()
secret = client.read_secret("stronghold/data/providers/credentials", "litellm")
print(secret)
```

## Backup and Restore

### Backup

```bash
# Create a snapshot
kubectl exec -n stronghold-platform deployment/stronghold-vault -- \
  vault operator raft snapshot save /tmp/snapshot.snap

# Copy snapshot locally
kubectl cp stronghold-platform/<pod>:/tmp/snapshot.snap ./backup.snap
```

### Restore

```bash
# Copy snapshot to pod
kubectl cp ./backup.snap stronghold-platform/<pod>:/tmp/snapshot.snap

# Restore from snapshot
kubectl exec -n stronghold-platform deployment/stronghold-vault -- \
  vault operator raft snapshot restore -force /tmp/snapshot.snap
```

## Security Best Practices

1. **Never store the root token in production** - Use unseal keys or Kubernetes secrets
2. **Enable audit logging** - Monitor all secret access
3. **Use namespace isolation** - Separate secrets per tenant/namespace
4. **Rotate credentials regularly** - Use dynamic secrets where possible
5. **Limit policy scope** - Follow principle of least privilege
6. **Enable TLS** - Use TLS for production deployments

## Troubleshooting

### Vault won't start

Check logs:

```bash
kubectl logs -n stronghold-platform deployment/stronghold-vault
```

### Cannot authenticate

Verify auth method is enabled and configured:

```bash
vault auth list
vault read auth/kubernetes/config
```

### Secrets not accessible

Check policies and roles:

```bash
vault policy list
vault read auth/kubernetes/role/stronghold-agent
```

### Storage issues

Check PVC status:

```bash
kubectl get pvc -n stronghold-platform
```

## Upgrading

```bash
helm upgrade stronghold-vault ./helm/vault -n stronghold-platform
```

## Uninstalling

```bash
helm uninstall stronghold-vault -n stronghold-platform

# Remove PVCs (optional)
kubectl delete pvc -n stronghold-platform data-stronghold-vault-0
```

## References

- [OpenBao Documentation](https://openbao.org/docs/)
- [Vault Best Practices](https://developer.hashicorp.com/vault/docs/operations/production-hardening)
- [Stronghold Architecture](https://github.com/stronghold/stronghold/blob/main/ARCHITECTURE.md)
