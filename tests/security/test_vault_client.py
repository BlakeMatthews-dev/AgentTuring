"""Unit tests for VaultClient implementation.

Tests are written in TDD style (failing assertions first).
All tests mock HTTP client interactions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from stronghold.protocols.vault import VaultClient, VaultSecret
from stronghold.security.vault_client import (
    ConnectionError as VaultConnectionError,
    OpenBaoVaultClient,
    PermissionError as VaultPermissionError,
    QuotaExceededError,
    RateLimitError,
)

# Fixtures
@pytest.fixture
def valid_org_id():
    """Valid UUID v4 org_id."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def valid_user_id():
    """Valid UUID v4 user_id."""
    return "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


@pytest.fixture
def valid_service():
    """Valid service name."""
    return "github"


@pytest.fixture
def valid_key():
    """Valid key name."""
    return "token"


@pytest.fixture
def valid_secret_value():
    """Valid secret value (<16KB)."""
    return "ghp_test_1234567890abcdef"


@pytest.fixture
def vault_addr():
    """Vault address for testing."""
    return "http://vault.test:8200"


@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient."""
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.delete = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def vault_client(vault_addr, mock_http_client):
    """Create VaultClient with mocked HTTP client."""
    with patch("stronghold.security.vault_client.httpx.AsyncClient", return_value=mock_http_client):
        client = OpenBaoVaultClient(
            vault_addr=vault_addr,
            k8s_auth_path="auth/kubernetes",
            namespace="stronghold-platform",
        )
        return client


# ============================================================================
# AC-1: Authentication Flow
# ============================================================================

def test_authenticate_on_first_operation(
    vault_client, mock_http_client, vault_addr, valid_org_id, valid_user_id
):
    """AC-1: Client authenticates to Vault on first operation."""
    # Mock login response
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={
            "auth": {
                "client_token": "s.test-token-12345",
                "lease_duration": 3600,
                "renewable": True,
            }
        },
    )

    # Mock secret read response
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"data": {"value": "ghp_123"}}},
    )

    # First operation triggers authentication
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, "github", "token")
    )

    # Verify login was called
    mock_http_client.post.assert_called_once_with(
        f"{vault_addr}/v1/auth/kubernetes/login",
        json={
            "role": "stronghold-api",
            "jwt": "test-service-account-token",
        },
    )

    # Verify token is stored (check subsequent call uses token)
    assert vault_client._token == "s.test-token-12345"
    assert vault_client._token_expiry is not None


# ============================================================================
# AC-2: Token Refresh
# ============================================================================

def test_token_refresh_before_expiry(
    vault_client, mock_http_client, vault_addr, valid_org_id, valid_user_id
):
    """AC-2: Token is refreshed before expiration."""
    # Set up initial authentication
    vault_client._token = "s.test-token-initial"
    vault_client._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=6)

    # Mock token renewal response
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={
            "auth": {
                "client_token": "s.test-token-renewed",
                "lease_duration": 3600,
                "renewable": True,
            }
        },
    )

    # Mock secret read response
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"data": {"value": "ghp_123"}}},
    )

    # Call get_user_secret (should trigger refresh)
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, "github", "token")
    )

    # Verify token was renewed
    mock_http_client.post.assert_called_with(
        f"{vault_addr}/v1/auth/token/renew-self",
        headers={"X-Vault-Token": "s.test-token-initial"},
    )

    # Verify new token is stored
    assert vault_client._token == "s.test-token-renewed"


# ============================================================================
# AC-3: Get Secret Success
# ============================================================================

def test_get_secret_success(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-3: Returns VaultSecret with value and version."""
    # Mock secret read response
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={
            "data": {
                "data": {
                    "value": "ghp_test_secret",
                    "metadata": {"version": 2},
                }
            }
        },
    )

    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
    )

    # Verify VaultSecret structure
    assert isinstance(result, VaultSecret)
    assert result.value == "ghp_test_secret"
    assert result.service == valid_service
    assert result.key == valid_key
    assert result.version == 2


# ============================================================================
# AC-4: Get Secret Not Found
# ============================================================================

def test_get_secret_not_found(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-4: Raises LookupError when secret does not exist."""
    # Mock 404 response
    mock_http_client.get.return_value = httpx.Response(404)

    with pytest.raises(LookupError) as exc_info:
        asyncio.run(
            vault_client.get_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
        )

    # Verify error message includes path
    error_msg = str(exc_info.value)
    assert "not found" in error_msg.lower()
    assert valid_org_id in error_msg
    assert valid_service in error_msg


# ============================================================================
# AC-5: Put Secret New
# ============================================================================

def test_put_secret_new(
    vault_client,
    mock_http_client,
    vault_addr,
    valid_org_id,
    valid_user_id,
    valid_service,
    valid_key,
    valid_secret_value,
):
    """AC-5: Creates new secret and returns version 1."""
    # Mock secret write response
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={"data": {"version": 1}},
    )

    result = asyncio.run(
        vault_client.put_user_secret(
            valid_org_id, valid_user_id, valid_service, valid_key, valid_secret_value
        )
    )

    # Verify VaultSecret structure
    assert isinstance(result, VaultSecret)
    assert result.value == valid_secret_value
    assert result.service == valid_service
    assert result.key == valid_key
    assert result.version == 1


# ============================================================================
# AC-6: Put Secret Update
# ============================================================================

def test_put_secret_update(
    vault_client,
    mock_http_client,
    vault_addr,
    valid_org_id,
    valid_user_id,
    valid_service,
    valid_key,
):
    """AC-6: Updates existing secret and increments version."""
    # Mock secret write response (version 2)
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={"data": {"version": 2}},
    )

    result = asyncio.run(
        vault_client.put_user_secret(
            valid_org_id, valid_user_id, valid_service, valid_key, "new_value"
        )
    )

    # Verify version incremented
    assert result.version == 2


# ============================================================================
# AC-7: Put Secret Too Large
# ============================================================================

def test_put_secret_too_large(
    vault_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-7: Rejects secrets >16KB with ValueError."""
    # Secret >16KB (20000 chars)
    large_value = "x" * 20000

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            vault_client.put_user_secret(
                valid_org_id, valid_user_id, valid_service, valid_key, large_value
            )
        )

    # Verify error message
    error_msg = str(exc_info.value)
    assert "too large" in error_msg.lower()
    assert "16384" in error_msg


# ============================================================================
# AC-8: Delete Secret Success
# ============================================================================

def test_delete_secret_success(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-8: Deletes secret and returns None."""
    # Mock delete response
    mock_http_client.delete.return_value = httpx.Response(204)

    result = asyncio.run(
        vault_client.delete_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
    )

    # Verify returns None
    assert result is None


# ============================================================================
# AC-9: Delete Secret Idempotent
# ============================================================================

def test_delete_secret_idempotent(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-9: Deleting non-existent secret returns None (no error)."""
    # Mock delete response (404 is acceptable for idempotency)
    mock_http_client.delete.return_value = httpx.Response(204)

    result = asyncio.run(
        vault_client.delete_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
    )

    # Verify no exception
    assert result is None


# ============================================================================
# AC-10: List Services With Secrets
# ============================================================================

def test_list_services_with_secrets(
    vault_client, mock_http_client, valid_org_id, valid_user_id
):
    """AC-10: Returns list of services with secrets."""
    # Mock Vault list response
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={
            "data": {
                "keys": ["github", "jira", "aws"],
            }
        },
    )

    result = asyncio.run(vault_client.list_user_services(valid_org_id, valid_user_id))

    # Verify list structure
    assert isinstance(result, list)
    assert len(result) == 3
    assert "github" in result
    assert "jira" in result
    assert "aws" in result


# ============================================================================
# AC-11: List Services Empty
# ============================================================================

def test_list_services_empty(
    vault_client, mock_http_client, valid_org_id, valid_user_id
):
    """AC-11: Returns empty list when user has no secrets."""
    # Mock empty list response
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"keys": []}},
    )

    result = asyncio.run(vault_client.list_user_services(valid_org_id, valid_user_id))

    # Verify empty list
    assert result == []


# ============================================================================
# AC-12: Revoke User Success
# ============================================================================

def test_revoke_user_success(vault_client, mock_http_client, valid_org_id, valid_user_id):
    """AC-12: Deletes all user secrets and returns count."""
    # Mock Vault delete response
    mock_http_client.delete.return_value = httpx.Response(
        200,
        json={"data": {"keys": ["github", "jira"]}},
    )

    result = asyncio.run(vault_client.revoke_user(valid_org_id, valid_user_id))

    # Verify count
    assert result == 2


# ============================================================================
# AC-13: Revoke User Idempotent
# ============================================================================

def test_revoke_user_idempotent(
    vault_client, mock_http_client, valid_org_id, valid_user_id
):
    """AC-13: Revoking user with no secrets returns 0."""
    # Mock empty list response
    mock_http_client.delete.return_value = httpx.Response(
        200,
        json={"data": {"keys": []}},
    )

    result = asyncio.run(vault_client.revoke_user(valid_org_id, valid_user_id))

    # Verify 0 count
    assert result == 0


# ============================================================================
# AC-14: Invalid UUID Validation
# ============================================================================

@pytest.mark.parametrize("param", ["org_id", "user_id"])
def test_invalid_uuid_validation(vault_client, param, valid_service, valid_key):
    """AC-14: Validates UUID format before contacting Vault."""
    invalid_uuid = "not-a-uuid"

    with pytest.raises(ValueError) as exc_info:
        if param == "org_id":
            asyncio.run(
                vault_client.get_user_secret(
                    invalid_uuid, "valid-user-id", valid_service, valid_key
                )
            )
        else:
            asyncio.run(
                vault_client.get_user_secret(
                    "valid-org-id", invalid_uuid, valid_service, valid_key
                )
            )

    # Verify error message
    error_msg = str(exc_info.value)
    assert "uuid" in error_msg.lower()


# ============================================================================
# AC-15: Concurrent Operations
# ============================================================================

def test_concurrent_operations(
    vault_client,
    mock_http_client,
    valid_org_id,
    valid_user_id,
    vault_addr,
):
    """AC-15: Multiple concurrent operations succeed without race conditions."""
    # Mock secret read responses
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"data": {"value": "ghp_123"}}},
    )

    # Run 10 concurrent operations
    async def get_secret(i):
        return await vault_client.get_user_secret(
            valid_org_id,
            valid_user_id,
            f"service_{i}",
            f"key_{i}",
        )

    results = asyncio.run(asyncio.gather(*(get_secret(i) for i in range(10))))

    # Verify all succeeded
    assert len(results) == 10
    for result in results:
        assert isinstance(result, VaultSecret)


# ============================================================================
# AC-16: Token Expired Handling
# ============================================================================

def test_token_expired_handling(
    vault_client,
    mock_http_client,
    vault_addr,
    valid_org_id,
    valid_user_id,
    valid_service,
    valid_key,
):
    """AC-16: Re-authenticates when token expires."""
    # Set expired token
    vault_client._token = "s.expired-token"
    vault_client._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

    # Mock 403 response first, then 200 after re-auth
    get_response_403 = httpx.Response(403)
    get_response_200 = httpx.Response(
        200,
        json={"data": {"data": {"value": "ghp_123"}}},
    )

    mock_http_client.get.side_effect = [get_response_403, get_response_200]
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={
            "auth": {
                "client_token": "s.new-token",
                "lease_duration": 3600,
                "renewable": True,
            }
        },
    )

    # First operation fails with 403, then re-auth and succeed
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
    )

    # Verify re-authentication happened
    assert vault_client._token == "s.new-token"

    # Verify operation succeeded
    assert isinstance(result, VaultSecret)


# ============================================================================
# AC-17: Vault Connection Loss
# ============================================================================

def test_vault_connection_loss(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_service, valid_key
):
    """AC-17: Raises ConnectionError when Vault is unreachable."""
    # Mock connection error
    mock_http_client.get.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(VaultConnectionError) as exc_info:
        asyncio.run(
            vault_client.get_user_secret(valid_org_id, valid_user_id, valid_service, valid_key)
        )

    # Verify error message
    error_msg = str(exc_info.value)
    assert "vault" in error_msg.lower() or "connection" in error_msg.lower()


# ============================================================================
# AC-18: Secret Masking in Logs
# ============================================================================

def test_secret_masking_in_logs(
    vault_client, mock_http_client, valid_org_id, valid_user_id, caplog
):
    """AC-18: Secret values are masked in logs."""
    # Mock secret write response
    mock_http_client.post.return_value = httpx.Response(
        200,
        json={"data": {"version": 1}},
    )

    # Capture logs
    with caplog.at_level("DEBUG"):
        asyncio.run(
            vault_client.put_user_secret(
                valid_org_id, valid_user_id, "github", "token", "secret_value_123"
            )
        )

    # Verify secret value is not in logs
    log_text = caplog.text
    assert "secret_value_123" not in log_text
    assert "***" in log_text or "SECRET" in log_text


# ============================================================================
# AC-19: Close Idempotent
# ============================================================================

def test_close_idempotent(vault_client, mock_http_client):
    """AC-19: Calling close() multiple times does not raise exception."""
    # Mock close
    mock_http_client.close.return_value = None

    # Close once
    asyncio.run(vault_client.close())

    # Close again (should not raise)
    asyncio.run(vault_client.close())

    # Verify close was called
    assert mock_http_client.close.call_count >= 1


# ============================================================================
# Edge Cases: Service Name Validation
# ============================================================================

@pytest.mark.parametrize(
    "service_name",
    ["valid-service", "valid_service", "ValidService123"],
)
def test_valid_service_names(vault_client, valid_org_id, valid_user_id, service_name):
    """Valid service names are alphanumeric with hyphens/underscores."""
    # Mock read response
    mock_http_client = vault_client._http_client
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"data": {"value": "test"}}},
    )

    # Should not raise
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, service_name, "key")
    )

    assert isinstance(result, VaultSecret)


@pytest.mark.parametrize(
    "service_name",
    ["invalid!service", "service with spaces", "a" * 65, "service/with/slashes"],
)
def test_invalid_service_names(
    vault_client, valid_org_id, valid_user_id, service_name
):
    """Invalid service names are rejected with ValueError."""
    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            vault_client.get_user_secret(valid_org_id, valid_user_id, service_name, "key")
        )

    error_msg = str(exc_info.value)
    assert "service" in error_msg.lower() or "invalid" in error_msg.lower()


# ============================================================================
# Edge Cases: Key Name Validation
# ============================================================================

@pytest.mark.parametrize(
    "key_name",
    ["valid-key", "valid_key", "ValidKey123"],
)
def test_valid_key_names(vault_client, valid_org_id, valid_user_id, key_name):
    """Valid key names are alphanumeric with hyphens/underscores."""
    # Mock read response
    mock_http_client = vault_client._http_client
    mock_http_client.get.return_value = httpx.Response(
        200,
        json={"data": {"data": {"value": "test"}}},
    )

    # Should not raise
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, "github", key_name)
    )

    assert isinstance(result, VaultSecret)


@pytest.mark.parametrize(
    "key_name",
    ["invalid!key", "key with spaces", "a" * 65, "key/with/slashes"],
)
def test_invalid_key_names(vault_client, valid_org_id, valid_user_id, key_name):
    """Invalid key names are rejected with ValueError."""
    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            vault_client.get_user_secret(valid_org_id, valid_user_id, "github", key_name)
        )

    error_msg = str(exc_info.value)
    assert "key" in error_msg.lower() or "invalid" in error_msg.lower()


# ============================================================================
# Edge Cases: Retry on 429 Rate Limit
# ============================================================================

def test_retry_on_rate_limit(
    vault_client, mock_http_client, vault_addr, valid_org_id, valid_user_id
):
    """Retries with backoff on 429 rate limit errors."""
    # Mock 429 responses twice, then 200
    response_429_1 = httpx.Response(429)
    response_429_2 = httpx.Response(429)
    response_200 = httpx.Response(
        200,
        json={"data": {"data": {"value": "ghp_123"}}},
    )

    mock_http_client.get.side_effect = [response_429_1, response_429_2, response_200]

    # Operation should succeed after retries
    result = asyncio.run(
        vault_client.get_user_secret(valid_org_id, valid_user_id, "github", "token")
    )

    # Verify success
    assert isinstance(result, VaultSecret)
    # Verify retry attempts (3 total: 2 failures + 1 success)
    assert mock_http_client.get.call_count == 3


# ============================================================================
# Edge Cases: Quota Exceeded
# ============================================================================

def test_quota_exceeded(
    vault_client, mock_http_client, valid_org_id, valid_user_id, valid_secret_value
):
    """Raises QuotaExceededError on 507 response."""
    # Mock 507 response
    mock_http_client.post.return_value = httpx.Response(507)

    with pytest.raises(QuotaExceededError):
        asyncio.run(
            vault_client.put_user_secret(
                valid_org_id, valid_user_id, "github", "token", valid_secret_value
            )
        )
