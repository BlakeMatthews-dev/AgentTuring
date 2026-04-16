# Deploying Stronghold on Azure AKS

Azure Kubernetes Service (AKS) is a Tier-1 supported platform per
[ADR-K8S-007](adr/ADR-K8S-007-distro-compatibility-matrix.md). This guide
walks through a production-ready deployment using Entra ID authentication,
Azure Workload Identity, and the Stronghold Helm chart.

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| AKS cluster | 1.29+ | OIDC issuer + Workload Identity enabled |
| Azure CLI | 2.61+ | `az aks` commands below require it |
| Helm | 3.14+ | Chart uses `kubeVersion: >=1.29.0-0` |
| kubectl | matching cluster version | |
| CNI | Azure CNI | Calico or Cilium network policy enforcement |
| DNS | A record for ingress | Or use nip.io for testing |

### Azure services used

- **AKS** — Kubernetes runtime (free control plane)
- **Azure Container Registry (ACR)** — container image storage
- **Azure Database for PostgreSQL Flexible Server** — managed postgres with pgvector
- **Entra ID (Azure AD)** — user authentication via OIDC/JWT
- **Azure Key Vault** — secrets (optional, via External Secrets Operator)
- **KEDA** — scale-to-zero for builders on spot nodes

## 1. Provision the AKS cluster

Two node pools: on-demand (core stack) and spot (burst builders).

```bash
RESOURCE_GROUP=stronghold-rg
CLUSTER_NAME=stronghold-aks
LOCATION=eastus2

az group create --name $RESOURCE_GROUP --location $LOCATION

# On-demand pool: 2x B2ms (2 vCPU / 8GB each) — core stack
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --node-count 2 \
  --node-vm-size Standard_B2ms \
  --network-plugin azure \
  --network-policy calico \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --enable-managed-identity \
  --generate-ssh-keys

# Spot pool: B2s (2 vCPU / 4GB), autoscaler 0→5 — burst builders
az aks nodepool add \
  --resource-group $RESOURCE_GROUP \
  --cluster-name $CLUSTER_NAME \
  --name spot \
  --node-count 0 \
  --min-count 0 \
  --max-count 5 \
  --node-vm-size Standard_B2s \
  --enable-cluster-autoscaler \
  --priority Spot \
  --eviction-policy Delete \
  --spot-max-price -1

az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME
```

### Install KEDA + nginx-ingress

```bash
# KEDA — scales builders from 0 on spot nodes
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace

# nginx-ingress (Standard LB, ~$18/mo)
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace
```

### 1b. Provision Azure Database for PostgreSQL Flexible Server

No in-cluster postgres. Use managed Flexible Server with pgvector.

```bash
PG_SERVER=stronghold-pg
PG_ADMIN=stronghold
PG_PASSWORD=$(openssl rand -base64 24)

az postgres flexible-server create \
  --resource-group $RESOURCE_GROUP \
  --name $PG_SERVER \
  --location $LOCATION \
  --admin-user $PG_ADMIN \
  --admin-password "$PG_PASSWORD" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0

# Allow AKS subnet access (get the AKS vnet/subnet)
AKS_SUBNET=$(az aks show -g $RESOURCE_GROUP -n $CLUSTER_NAME \
  --query 'agentPoolProfiles[0].vnetSubnetId' -o tsv)
az postgres flexible-server firewall-rule create \
  --resource-group $RESOURCE_GROUP \
  --name $PG_SERVER \
  --rule-name aks-access \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 255.255.255.255  # Tighten to AKS egress IP in production

# Enable pgvector extension
az postgres flexible-server parameter set \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER \
  --name azure.extensions \
  --value vector

# Create the databases
az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER \
  --database-name stronghold

az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP \
  --server-name $PG_SERVER \
  --database-name phoenix

# Connect and enable extensions (requires psql)
PG_HOST="${PG_SERVER}.postgres.database.azure.com"
PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -U "$PG_ADMIN" -d stronghold \
  -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"

echo "PG_HOST=$PG_HOST"
echo "PG_PASSWORD=$PG_PASSWORD"
```

### 1c. Create the database secret

```bash
kubectl create namespace stronghold-platform

kubectl -n stronghold-platform create secret generic postgres-flexible-credentials \
  --from-literal=POSTGRES_USER=$PG_ADMIN \
  --from-literal=POSTGRES_PASSWORD="$PG_PASSWORD" \
  --from-literal=POSTGRES_DB=stronghold
```

## 2. Set up Azure Container Registry

```bash
ACR_NAME=strongholdacr  # Must be globally unique

az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Standard

# Attach ACR to AKS (grants AcrPull to the kubelet identity)
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --attach-acr $ACR_NAME

# Build and push the Stronghold image
az acr build --registry $ACR_NAME --image stronghold/stronghold-api:latest .
```

## 3. Register the Entra ID application

Stronghold validates JWTs issued by Entra ID. You need an app registration:

```bash
# Create app registration
az ad app create --display-name stronghold-api \
  --sign-in-audience AzureADMyOrg

# Note the appId (this is your CLIENT_ID)
CLIENT_ID=$(az ad app list --display-name stronghold-api --query '[0].appId' -o tsv)

TENANT_ID=$(az account show --query tenantId -o tsv)

echo "ENTRA_TENANT_ID=$TENANT_ID"
echo "ENTRA_CLIENT_ID=$CLIENT_ID"
```

### Define app roles

Add Stronghold RBAC roles to the app registration (Admin, Engineer, Operator,
Viewer) via the Azure Portal under **App registrations > stronghold-api > App
roles**, or via the manifest:

| Role value | Description |
|---|---|
| `Stronghold.Admin` | Full platform administration |
| `Stronghold.Engineer` | Code agents, tool creation |
| `Stronghold.Operator` | Device control, runbooks |
| `Stronghold.Viewer` | Read-only search and observation |

## 4. Configure Azure Workload Identity

Workload Identity lets pods authenticate to Azure services without storing
credentials. This replaces the deprecated pod-managed identity (aad-pod-identity).

```bash
AKS_OIDC_ISSUER=$(az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# Create a managed identity for Stronghold workloads
az identity create \
  --name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

IDENTITY_CLIENT_ID=$(az identity show \
  --name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --query clientId -o tsv)

# Create federated credential for the stronghold-api service account
az identity federated-credential create \
  --name stronghold-api-fc \
  --identity-name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:stronghold-platform:stronghold-stronghold-api" \
  --audience "api://AzureADTokenExchange"

# Create federated credential for LiteLLM (if it needs Azure OpenAI access)
az identity federated-credential create \
  --name litellm-fc \
  --identity-name stronghold-identity \
  --resource-group $RESOURCE_GROUP \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:stronghold-platform:stronghold-stronghold-litellm" \
  --audience "api://AzureADTokenExchange"
```

### Grant permissions to the managed identity

If using Azure Key Vault for secrets:

```bash
KV_NAME=stronghold-kv

az keyvault set-policy --name $KV_NAME \
  --secret-permissions get list \
  --object-id $(az identity show --name stronghold-identity \
    --resource-group $RESOURCE_GROUP --query principalId -o tsv)
```

If using Azure OpenAI:

```bash
AOAI_RESOURCE_ID=$(az cognitiveservices account show \
  --name <your-aoai-resource> \
  --resource-group <your-rg> \
  --query id -o tsv)

az role assignment create \
  --assignee-object-id $(az identity show --name stronghold-identity \
    --resource-group $RESOURCE_GROUP --query principalId -o tsv) \
  --role "Cognitive Services OpenAI User" \
  --scope "$AOAI_RESOURCE_ID"
```

## 5. Deploy with Helm

```bash
helm upgrade --install stronghold deploy/helm/stronghold \
  --namespace stronghold-platform --create-namespace \
  -f deploy/helm/stronghold/values-vanilla-k8s.yaml \
  -f deploy/helm/stronghold/values-aks.yaml \
  --set auth.entraId.tenantId="$TENANT_ID" \
  --set auth.entraId.clientId="$CLIENT_ID" \
  --set serviceAccounts.strongholdApi.annotations."azure\.workload\.identity/client-id"="$IDENTITY_CLIENT_ID" \
  --set serviceAccounts.litellm.annotations."azure\.workload\.identity/client-id"="$IDENTITY_CLIENT_ID" \
  --set strongholdApi.image.registry="${ACR_NAME}.azurecr.io" \
  --set strongholdApi.image.tag="latest" \
  --set builders.image.registry="${ACR_NAME}.azurecr.io" \
  --set builders.image.tag="latest" \
  --set ingressRoutes.stronghold.host="stronghold.yourdomain.com"
```

For dev (single replicas, relaxed security):

```bash
helm upgrade --install stronghold deploy/helm/stronghold \
  --namespace stronghold-platform --create-namespace \
  -f deploy/helm/stronghold/values-vanilla-k8s.yaml \
  -f deploy/helm/stronghold/values-aks.yaml \
  -f deploy/helm/stronghold/values-dev.yaml \
  --set auth.entraId.tenantId="$TENANT_ID" \
  --set auth.entraId.clientId="$CLIENT_ID" \
  --set strongholdApi.image.registry="${ACR_NAME}.azurecr.io" \
  --set strongholdApi.image.tag="latest" \
  --set builders.image.registry="${ACR_NAME}.azurecr.io" \
  --set builders.image.tag="latest"
```

## 6. Verify the deployment

```bash
# Wait for pods
kubectl -n stronghold-platform get pods -w

# Check health
kubectl -n stronghold-platform port-forward svc/stronghold-stronghold-api 8100:8100
curl http://localhost:8100/health

# Verify Workload Identity injection (pods should have AZURE_* env vars)
kubectl -n stronghold-platform exec deploy/stronghold-stronghold-api \
  -- env | grep AZURE_

# Test network policies
kubectl run netpol-test --image=busybox --rm -it --restart=Never \
  -n default -- wget -qO- --timeout=3 \
  http://stronghold-stronghold-api.stronghold-platform:8100/health
# ^ Should timeout/fail (default namespace blocked by network policy)
```

## 7. Azure Key Vault integration (optional)

For production, use External Secrets Operator (ESO) to pull secrets from
Azure Key Vault instead of Kubernetes Secrets:

```bash
# Install ESO
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  --namespace external-secrets --create-namespace

# Create a SecretStore pointing to Azure Key Vault
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: azure-kv
  namespace: stronghold-platform
spec:
  provider:
    azurekv:
      authType: WorkloadIdentity
      vaultUrl: "https://${KV_NAME}.vault.azure.net"
      serviceAccountRef:
        name: stronghold-stronghold-api
EOF

# Create ExternalSecret for Stronghold secrets
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: stronghold-secrets
  namespace: stronghold-platform
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-kv
    kind: SecretStore
  target:
    name: stronghold-secrets
  data:
    - secretKey: ROUTER_API_KEY
      remoteRef:
        key: stronghold-router-api-key
    - secretKey: LITELLM_MASTER_KEY
      remoteRef:
        key: stronghold-litellm-master-key
EOF
```

## 8. Azure OpenAI with LiteLLM

To route through Azure OpenAI instead of (or alongside) other providers,
add models to the LiteLLM config. The Helm chart mounts the config from
`deploy/helm/stronghold/files/litellm_config.yaml`.

Example Azure OpenAI model entry:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: https://<your-resource>.openai.azure.com/
      api_version: "2024-08-01-preview"
      # With Workload Identity, no API key needed:
      # LiteLLM uses DefaultAzureCredential automatically
```

## Architecture on AKS

```
                       Internet
                          |
                     nginx-ingress
                  (Standard Load Balancer)
                          |
             +------------+------------+
             |                         |
      stronghold-api (x2)       litellm (x1)      ← on-demand nodes
             |                    |
             +--------+-----------+
                      |
         Azure Flexible Server (B1ms)
          PostgreSQL 16 + pgvector
                      |
               phoenix (x1)

   stronghold-builders (x1)    ← on-demand, always warm
   stronghold-builders-spot    ← spot nodes, KEDA 0→5

Auth:    Entra ID (JWT) ──> stronghold-api
Secrets: Azure Key Vault ──> ESO ──> K8s Secrets
Identity: Azure Workload Identity (no stored credentials)
Scaling: HPA (api pods) + KEDA (builders) + cluster autoscaler (spot nodes)
```

## Cost estimates

### Dev (idle, spot pool at 0)

| Resource | SKU | Estimated monthly cost |
|---|---|---|
| AKS on-demand (2x B2ms) | Pay-as-you-go | ~$120 |
| AKS spot pool (0 at idle) | Spot | ~$0 |
| Azure Flexible Server | B1ms burstable | ~$13 |
| Azure Load Balancer | Standard (nginx-ingress) | ~$18 |
| Azure Disk (2Gi workspace) | managed-csi | ~$1 |
| ACR | Standard | ~$5 |
| AKS control plane | Free tier | $0 |
| **Total at idle** | | **~$157/month** |

Under load with 3 spot builders active: +~$35/month for spot B2s nodes.

### Production (dedicated compute, AGIC)

| Resource | SKU | Estimated monthly cost |
|---|---|---|
| AKS on-demand (3x D4s_v5) | Pay-as-you-go | ~$400 |
| AKS spot pool (0-5x B2s) | Spot (~60% discount) | ~$0-50 |
| Azure Flexible Server | GP D2s_v3 | ~$100 |
| Application Gateway (v2) | Standard_v2 | ~$250 |
| ACR | Standard | ~$5 |
| **Total** | | **~$755/month (idle) — ~$805/month (loaded)** |

## Troubleshooting

**Pods stuck in `CrashLoopBackOff`:** Check logs with
`kubectl -n stronghold-platform logs deploy/stronghold-stronghold-api`. Common
causes: missing `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`, database not ready.

**Workload Identity not injecting:** Verify the federated credential subject
matches `system:serviceaccount:<namespace>:<sa-name>` exactly. Check with
`az identity federated-credential list --identity-name stronghold-identity --resource-group <rg>`.

**NetworkPolicy blocking legitimate traffic:** Ensure your ingress controller
namespace has the label `networking.k8s.io/ingress=true`, or set
`networkPolicy.ingressOpen=true` for testing.

**AGIC not picking up Ingress:** Ensure the AGIC addon is enabled and the
`ingressClassName` is `azure-application-gateway`. Check AGIC logs:
`kubectl logs -n kube-system -l app=ingress-appgw`.

**Flexible Server connection refused:** Ensure the firewall rule allows AKS
egress IPs. Check with `az postgres flexible-server firewall-rule list`.
Verify the `postgres-flexible-credentials` secret has the correct host
(`<server>.postgres.database.azure.com`).

**pgvector extension not found:** Run
`az postgres flexible-server parameter set --name azure.extensions --value vector`
then connect via psql and run `CREATE EXTENSION IF NOT EXISTS vector;`.

**KEDA not scaling builders:** Check KEDA operator logs:
`kubectl -n keda logs deploy/keda-operator`. Verify the Prometheus address
in the ScaledObject is reachable. Check `/metrics` on stronghold-api returns
`builders_queue_actionable`.

**Spot builders evicted frequently:** This is expected — spot VMs can be
reclaimed at any time. The cluster autoscaler provisions new spot nodes.
Work in progress is lost on eviction; the pipeline retries from the last
completed stage.
