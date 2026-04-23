# VaultClient Implementation Specification

**Status**: DRAFT  
**Phase**: 2 - HIGH Priority  
**Related ADR**: ADR-K8S-018 (Per-User Credential Vault)  
**Protocol**: `src/stronghold/protocols/vault.py`

---

## 1. Purpose

Provide per-user credential storage and retrieval for tool executors. Enables Stronghold to act on behalf of individual users with their own GitHub PATs, JIRA tokens, AWS credentials, etc., without exposing these secrets to the application or other users.

**Path Convention**: `users/{org_id}/{user_id}/{service}/{key}`

---

## 2. API Contract

### 2.1 Class: OpenBaoVaultClient

```python
class OpenBaoVaultClient(VaultClient):
    """Production Vault client using OpenBao with Kubernetes auth."""

    def __init__(
        self,
        vault_addr: str,
        k8s_auth_path: str = "auth/kubernetes",
        namespace: str = "stronghold-system",
        token_refresh_interval: int = 300,
    ) -> None:
        """Initialize Vault client.

        Args:
            vault_addr: Full Vault HTTP address (e.g., "http://vault.stronghold-system:8200")
            k8s_auth_path: Kubernetes auth mount path in Vault
            namespace: Kubernetes namespace for service account
            token_refresh_interval: Seconds between token refreshes (default: 300 = 5 min)
        """
```

### 2.2 Method: async get_user_secret()

**Signature**:
```python
async def get_user_secret(
    self,
    org_id: str,
    user_id: str,
    service: str,
    key: str,
) -> VaultSecret:
```

**Behavior**:
1. Authenticate to Vault using service account token if not already authenticated
2. Read secret at path `users/{org_id}/{user_id}/{service}/{key}`
3. Return `VaultSecret` with value, metadata, version

**Success Cases**:
- Secret exists and is accessible → Return `VaultSecret(value=..., service=..., key=..., version=N)`

**Error Cases**:
| Scenario | Exception | HTTP Status |
|----------|------------|--------------|
| Secret does not exist | `LookupError` | 404 (Vault API) |
| Not authenticated | `PermissionError` | 403 (Vault API) |
| Vault connection failed | `ConnectionError` | 500 (internal) |
| Invalid org_id/user_id format | `ValueError` | 400 (validation) |

**Validation Rules**:
- `org_id`: UUID format only (v4), reject others before calling Vault
- `user_id`: UUID format only (v4), reject others
- `service`: Alphanumeric + hyphens/underscores, max 64 chars
- `key`: Alphanumeric + hyphens/underscores, max 64 chars

### 2.3 Method: async put_user_secret()

**Signature**:
```python
async def put_user_secret(
    self,
    org_id: str,
    user_id: str,
    service: str,
    key: str,
    value: str,
) -> VaultSecret:
```

**Behavior**:
1. Validate input parameters (format, length)
2. Authenticate if needed
3. Write secret to path `users/{org_id}/{user_id}/{service}/{key}`
4. Increment secret version
5. Return `VaultSecret` with new version

**Success Cases**:
- New secret created → Return `VaultSecret(value=..., service=..., key=..., version=1)`
- Existing secret updated → Return `VaultSecret(value=..., service=..., key=..., version=N+1)`

**Error Cases**:
| Scenario | Exception | HTTP Status |
|----------|------------|--------------|
| Validation failed | `ValueError` | 400 |
| Not authenticated | `PermissionError` | 403 |
| Vault connection failed | `ConnectionError` | 500 |
| Quota exceeded (Vault storage) | `QuotaExceededError` | 507 |

**Validation Rules**:
- Same as `get_user_secret()` for org_id/user_id/service/key
- `value`: Max 16KB (16384 chars), reject larger

**Security Requirements**:
- Mask secret value in logs (replace with `*****` or `***SECRET***`)
- Never log full secret even in debug mode

### 2.4 Method: async delete_user_secret()

**Signature**:
```python
async def delete_user_secret(
    self,
    org_id: str,
    user_id: str,
    service: str,
    key: str,
) -> None:
```

**Behavior**:
1. Validate input parameters
2. Authenticate if needed
3. Delete secret at path `users/{org_id}/{user_id}/{service}/{key}`
4. Return `None` (success is silent)

**Success Cases**:
- Secret exists → Deleted, return `None`
- Secret does not exist → Idempotent, return `None` (no error)

**Error Cases**:
| Scenario | Exception | HTTP Status |
|----------|------------|--------------|
| Validation failed | `ValueError` | 400 |
| Not authenticated | `PermissionError` | 403 |
| Vault connection failed | `ConnectionError` | 500 |

### 2.5 Method: async list_user_services()

**Signature**:
```python
async def list_user_services(
    self,
    org_id: str,
    user_id: str,
) -> list[str]:
```

**Behavior**:
1. Validate org_id/user_id
2. Authenticate if needed
3. List all services under `users/{org_id}/{user_id}/`
4. Return list of service names (strings)

**Success Cases**:
- User has secrets → Return `["github", "jira", "aws"]`
- User has no secrets → Return `[]` (empty list, no error)

**Error Cases**:
| Scenario | Exception | HTTP Status |
|----------|------------|--------------|
| Validation failed | `ValueError` | 400 |
| Not authenticated | `PermissionError` | 403 |
| Vault connection failed | `ConnectionError` | 500 |

### 2.6 Method: async revoke_user()

**Signature**:
```python
async def revoke_user(
    self,
    org_id: str,
    user_id: str,
) -> int:
```

**Behavior**:
1. Validate org_id/user_id
2. Authenticate if needed
3. Recursively delete all secrets under `users/{org_id}/{user_id}/`
4. Return count of deleted secrets

**Success Cases**:
- User has secrets → Delete all, return count (e.g., `5`)
- User has no secrets → Return `0` (idempotent)

**Error Cases**:
| Scenario | Exception | HTTP Status |
|----------|------------|--------------|
| Validation failed | `ValueError` | 400 |
| Not authenticated | `PermissionError` | 403 |
| Vault connection failed | `ConnectionError` | 500 |

**Use Case**: Offboarding - revoke all user secrets when user leaves org.

### 2.7 Method: async close()

**Signature**:
```python
async def close(self) -> None:
```

**Behavior**:
1. Close HTTP client connections
2. Clear cached Vault token
3. Stop token refresh background task (if any)
4. Idempotent (can call multiple times safely)

**Success Cases**:
- Always returns `None`, never raises

---

## 3. Authentication Flow

### 3.1 Kubernetes Authentication

**Mechanism**:
1. Read service account token from `/var/run/secrets/kubernetes.io/serviceaccount/token`
2. Send POST to `http://vault:8200/v1/auth/{k8s_auth_path}/login`
3. Payload:
```json
{
  "role": "stronghold-api",
  "jwt": "<service-account-token>"
}
```
4. Receive response with Vault client token:
```json
{
  "auth": {
    "client_token": "s.xxxxxxxxx",
    "lease_duration": 3600,
    "renewable": true
  }
}
```
5. Store token for subsequent requests

### 3.2 Token Refresh

**Strategy**: Proactive refresh before expiration

**Trigger**: Refresh token when `token_age >= token_refresh_interval` (default: 300s)

**Refresh Flow**:
1. Send POST to `/v1/auth/token/renew-self`
2. Header: `X-Vault-Token: <current-token>`
3. Receive renewed token with new lease_duration
4. Update stored token

**Error Handling on Refresh**:
- Refresh fails (403, 500, timeout) → Log warning, continue with old token
- Token expired (403 on next operation) → Re-authenticate (full login flow)

### 3.3 Token Storage

**In-Memory Storage** (production):
```python
self._token: str | None = None
self._token_expiry: float | None = None  # Unix timestamp
self._http_client: AsyncClient | None = None
```

**Thread Safety**: Use `asyncio.Lock` to prevent race conditions on token refresh

---

## 4. Error Handling

### 4.1 Vault API Error Mapping

| Vault HTTP Status | Exception | Retry |
|------------------|------------|--------|
| 400 Bad Request | `ValueError` | No (validation error) |
| 403 Forbidden | `PermissionError` | Yes (re-auth) |
| 404 Not Found | `LookupError` | No |
| 429 Too Many Requests | `RateLimitError` | Yes (backoff) |
| 500 Internal Server Error | `ConnectionError` | Yes (exponential backoff) |
| 507 Insufficient Storage | `QuotaExceededError` | No |

### 4.2 Retry Policy

**Retryable Errors**: 403 (auth), 429 (rate limit), 500 (server error)

**Backoff Strategy**:
- Attempt 1: Immediate
- Attempt 2: Wait 1s
- Attempt 3: Wait 5s
- Attempt 4: Wait 10s
- Attempt 5: Fail (max 5 retries)

**Jitter**: Add random ±20% to backoff to avoid thundering herd

### 4.3 Connection Pooling

**HTTP Client**: Use `httpx.AsyncClient` with connection pool

**Configuration**:
```python
timeout = httpx.Timeout(10.0, connect=5.0)
limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
```

---

## 5. Edge Cases

### 5.1 Concurrent Operations

**Scenario**: Two coroutines call `get_user_secret()` for same secret simultaneously

**Expected Behavior**:
- Both requests succeed
- No race condition on token refresh
- No connection pool exhaustion

**Implementation**:
- Use separate HTTP client per instance (thread-safe)
- Token refresh protected by `asyncio.Lock`

### 5.2 Token Expired During Operation

**Scenario**: Token expires mid-operation (long-running `put_user_secret()`)

**Expected Behavior**:
- Operation fails with 403
- Client re-authenticates
- User must retry operation

**Implementation**:
- Check token expiry before each operation
- If expired, refresh proactively

### 5.3 Vault Connection Loss

**Scenario**: Vault pod crashes or network partition

**Expected Behavior**:
- Current operation raises `ConnectionError`
- Client remains in usable state (auto-reconnect on next operation)
- Token is not cached (must re-auth on reconnect)

**Implementation**:
- HTTP client handles connection errors
- No persistent state outside Vault

### 5.4 Invalid UUID Format

**Scenario**: Caller passes `org_id="invalid"` instead of UUID

**Expected Behavior**:
- Immediate `ValueError` before calling Vault
- No network request made
- Error message: "org_id must be UUID v4 format"

**Implementation**:
- Validate UUID format on public method entry
- Use `uuid.UUID(value, version=4)` which raises `ValueError` on invalid format

### 5.5 Secret Too Large

**Scenario**: Caller passes `value` > 16KB

**Expected Behavior**:
- Immediate `ValueError`
- No network request made
- Error message: "Secret value too large (max 16KB)"

**Implementation**:
- Check `len(value)` before sending
- Reject with clear error

### 5.6 User Offboarding (Revoke During Active Use)

**Scenario**: User has active operations in progress, admin calls `revoke_user()`

**Expected Behavior**:
- `revoke_user()` deletes all secrets synchronously
- In-flight operations fail with `LookupError` (404)
- No partial state or orphaned secrets

**Implementation**:
- `revoke_user()` is synchronous deletion in Vault
- Operations happen independently (no locking in client layer)

---

## 6. Security Requirements

### 6.1 Input Validation

**Mandatory**: All public methods validate input before contacting Vault

**Validation Rules**:
| Parameter | Rule | Error |
|-----------|-------|-------|
| org_id | UUID v4 format | ValueError |
| user_id | UUID v4 format | ValueError |
| service | Alphanumeric + `_-`, max 64 chars | ValueError |
| key | Alphanumeric + `_-`, max 64 chars | ValueError |
| value | Max 16384 chars | ValueError |

### 6.2 Secret Masking

**Rule**: Never log secret values in cleartext

**Implementation**:
```python
logger.debug("Writing secret for service=%s, key=%s, value=***", service, key)
logger.debug("Read secret: service=%s, key=%s, value=***", service, key)
```

**Audit Logs**: Log only metadata (org_id, user_id, service, key), not value

### 6.3 Least Privilege

**K8s Service Account**: Minimal RBAC
- Role: `stronghold-api-vault-reader`
- Namespace: `stronghold-platform`
- Permissions: Read `secrets` from `stronghold-system` namespace only

**Vault Policy**: Namespace-scoped
- Can read/write/delete only under `users/{org_id}/...`
- Cannot access other users' secrets
- Cannot access Vault admin paths

### 6.4 TLS Verification

**Development** (`dev` env):
- `VAULT_ADDR` starts with `http://` → Skip TLS verification

**Production** (`prod` env):
- `VAULT_ADDR` starts with `https://` → Verify TLS certificates
- Reject self-signed certificates

---

## 7. Acceptance Criteria

### AC-1: Authentication Flow

**Given** Valid Kubernetes service account token
**When** `OpenBaoVaultClient` is instantiated and first operation is called
**Then**:
- Client authenticates to Vault via `/v1/auth/kubernetes/login`
- Token is stored in memory
- Token has expiration time (lease_duration + buffer)
- Subsequent operations use stored token without re-authenticating

### AC-2: Token Refresh

**Given** Authenticated Vault client with token expiring in 5 minutes
**When** Token age reaches 5 minutes
**Then**:
- Token is refreshed via `/v1/auth/token/renew-self`
- New token has extended lease_duration
- Operations continue without 403 errors

### AC-3: Get Secret Success

**Given** Existing secret at `users/{org_id}/{user_id}/github/token`
**When** `get_user_secret(org_id, user_id, "github", "token")` is called
**Then**:
- Returns `VaultSecret(value="ghp_xxx", service="github", key="token", version=2)`
- No network errors
- Response time < 100ms (local Vault)

### AC-4: Get Secret Not Found

**Given** No secret at path `users/{org_id}/{user_id}/github/token`
**When** `get_user_secret(org_id, user_id, "github", "token")` is called
**Then**:
- Raises `LookupError`
- Error message: "Secret not found at users/{org_id}/{user_id}/github/token"
- No retry (immediate failure)

### AC-5: Put Secret New

**Given** No existing secret at path
**When** `put_user_secret(org_id, user_id, "github", "token", "ghp_xxx")` is called
**Then**:
- Secret is created at Vault path
- Returns `VaultSecret(value="ghp_xxx", service="github", key="token", version=1)`
- Audit log records creation (metadata only, not value)

### AC-6: Put Secret Update

**Given** Existing secret at version 1
**When** `put_user_secret(org_id, user_id, "github", "token", "ghp_new")` is called
**Then**:
- Secret is updated at Vault path
- Returns `VaultSecret(value="ghp_new", service="github", key="token", version=2)`
- Old version is inaccessible

### AC-7: Put Secret Too Large

**Given** Secret value of 20KB (>16KB limit)
**When** `put_user_secret(..., value="x"*20000)` is called
**Then**:
- Raises `ValueError`
- Error message: "Secret value too large (max 16384 chars, got 20000)"
- No network request to Vault

### AC-8: Delete Secret Success

**Given** Existing secret at path
**When** `delete_user_secret(org_id, user_id, "github", "token")` is called
**Then**:
- Secret is deleted from Vault
- Returns `None`
- Subsequent `get_user_secret()` raises `LookupError`

### AC-9: Delete Secret Idempotent

**Given** No secret at path
**When** `delete_user_secret(org_id, user_id, "github", "token")` is called
**Then**:
- Returns `None` (no error)
- No exception raised

### AC-10: List Services With Secrets

**Given** Secrets at `users/{org_id}/{user_id}/github/` and `users/{org_id}/{user_id}/jira/`
**When** `list_user_services(org_id, user_id)` is called
**Then**:
- Returns `["github", "jira"]`
- Order is not guaranteed (set-like behavior)

### AC-11: List Services Empty

**Given** No secrets for user
**When** `list_user_services(org_id, user_id)` is called
**Then**:
- Returns `[]` (empty list)
- No exception raised

### AC-12: Revoke User Success

**Given** User has 5 secrets across services
**When** `revoke_user(org_id, user_id)` is called
**Then**:
- All 5 secrets are deleted
- Returns `5` (count)
- Subsequent `list_user_services()` returns `[]`

### AC-13: Revoke User Idempotent

**Given** User has no secrets
**When** `revoke_user(org_id, user_id)` is called
**Then**:
- Returns `0` (no secrets deleted)
- No exception raised

### AC-14: Invalid UUID Validation

**Given** `org_id="not-a-uuid"`
**When** Any method is called with this org_id
**Then**:
- Raises `ValueError`
- Error message: "org_id must be UUID v4 format"
- No network request to Vault

### AC-15: Concurrent Operations

**Given** Authenticated Vault client
**When** 10 concurrent coroutines call `get_user_secret()` for different secrets
**Then**:
- All 10 operations succeed
- No race conditions or token refresh conflicts
- Total time < 2 seconds (with connection pool)

### AC-16: Token Expired Handling

**Given** Authenticated Vault client with expired token
**When** Any operation is called
**Then**:
- Operation fails with 403 on first attempt
- Client re-authenticates (full login flow)
- Operation can be retried successfully

### AC-17: Vault Connection Loss

**Given** Vault pod is not reachable
**When** Any operation is called
**Then**:
- Raises `ConnectionError`
- Error message includes Vault address
- Client remains in usable state for next operation

### AC-18: Secret Masking in Logs

**Given** Debug logging enabled
**When** `put_user_secret(..., value="secret123")` is called
**Then**:
- Log contains `value=***` or `value=***SECRET***`
- Log does NOT contain "secret123"
- Audit log contains only metadata (org_id, user_id, service, key)

### AC-19: Close Idempotent

**Given** Vault client already closed
**When** `close()` is called again
**Then**:
- No exception raised
- Returns `None`

### AC-20: Performance Requirements

**Given** Vault is healthy and responsive
**When** `get_user_secret()` is called 100 times sequentially
**Then**:
- Average response time < 100ms (local Vault)
- 99th percentile < 200ms
- No memory leaks (heap size stable)

---

## 8. Testing Strategy

### 8.1 Unit Tests

**File**: `tests/security/test_vault_client.py`

**Test Cases**:
- Authentication flow (mock Vault API)
- Token refresh (mock time, check renewal)
- Get secret (success, not found, validation error)
- Put secret (new, update, too large)
- Delete secret (success, idempotent)
- List services (with secrets, empty)
- Revoke user (success, idempotent)
- UUID validation
- Secret value size validation
- Connection error handling
- Token expiry handling
- Concurrent operations (use `asyncio.gather`)

**Fixtures**:
- `mock_vault_http_client`: Returns predefined responses
- `valid_org_id`: UUID string fixture
- `valid_user_id`: UUID string fixture
- `vault_client`: Real client with mocked HTTP

### 8.2 Integration Tests

**File**: `tests/integration/test_vault_integration.py`

**Prerequisites**:
- Running OpenBao/Vault instance
- Kubernetes auth configured
- Service account with correct RBAC

**Test Cases** (marked with `@pytest.mark.integration`):
- Real authentication flow
- Real secret CRUD operations
- Real token refresh
- Real error handling (connection loss, permission errors)

**Environment Variables**:
- `VAULT_ADDR`: http://localhost:8200
- `VAULT_K8S_AUTH_PATH`: auth/kubernetes
- `VAULT_NAMESPACE`: default

### 8.3 Security Tests

**File**: `tests/security/test_vault_security.py`

**Test Cases**:
- Input validation (invalid UUIDs, large values)
- Secret masking in logs (capture logs, check for cleartext)
- Permission boundary (cannot access other users' secrets)
- TLS verification (production env rejects bad certs)

---

## 9. Implementation Dependencies

**Required Files**:
- `src/stronghold/security/vault_client.py` (new)
- `src/stronghold/protocols/vault.py` (exists)
- `tests/security/test_vault_client.py` (new)
- `tests/security/test_vault_security.py` (new)
- `tests/fakes.py` (extend `FakeVaultClient` for testing)

**External Dependencies**:
- `httpx` (async HTTP client)
- `uuid` (UUID validation)
- `asyncio` (lock for token refresh)

**Infrastructure**:
- Vault deployment template (`vault-deployment.yaml` - exists)
- K8s RBAC for Vault authentication (to be created)
- Service account with role binding (to be created)

---

## 10. Open Questions

1. **Token Storage**: Should we support persistent token caching across restarts? (Current: no, re-auth on restart)
2. **Retry Count**: Is 5 retries appropriate? Should this be configurable?
3. **Backoff Strategy**: Should we use exponential backoff (1s, 2s, 4s, 8s) instead of fixed?
4. **Connection Pool Size**: Are 20 keepalive / 100 max connections appropriate for expected load?
5. **Audit Logging**: Should we write to audit log (InMemoryAuditLog) for all secret operations?

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-21  
**Status**: Ready for implementation and test creation
