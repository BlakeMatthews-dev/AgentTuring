"""Tests for MCPDeployerClient (ADR-K8S-025/026)."""

from __future__ import annotations

from stronghold.sandbox.deployer import FakeMCPDeployerClient


async def test_spawn_returns_pod_metadata() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme", user_id="alice")
    assert "pod_id" in result
    assert result["status"] == "running"
    assert result["tenant_id"] == "acme"
    assert result["template"] == "sandbox.shell"
    assert "endpoint" in result


async def test_spawn_unique_ids() -> None:
    deployer = FakeMCPDeployerClient()
    r1 = await deployer.spawn("sandbox.shell", tenant_id="acme")
    r2 = await deployer.spawn("sandbox.python", tenant_id="acme")
    assert r1["pod_id"] != r2["pod_id"]


async def test_reap_existing_pod() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    assert await deployer.reap(result["pod_id"]) is True


async def test_reap_nonexistent_pod() -> None:
    deployer = FakeMCPDeployerClient()
    assert await deployer.reap("nonexistent") is False


async def test_status_running_pod() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    status = await deployer.status(result["pod_id"])
    assert status["status"] == "running"


async def test_status_not_found() -> None:
    deployer = FakeMCPDeployerClient()
    status = await deployer.status("nonexistent")
    assert status["status"] == "not_found"


async def test_list_active_all() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.spawn("sandbox.python", tenant_id="evil")
    pods = await deployer.list_active()
    assert len(pods) == 2


async def test_list_active_filtered() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.spawn("sandbox.python", tenant_id="evil")
    pods = await deployer.list_active(tenant_id="acme")
    assert len(pods) == 1
    assert pods[0]["tenant_id"] == "acme"


async def test_health() -> None:
    deployer = FakeMCPDeployerClient()
    assert await deployer.health() is True


async def test_close() -> None:
    deployer = FakeMCPDeployerClient()
    await deployer.close()  # Should not raise


async def test_spawn_with_env_overrides() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn(
        "sandbox.shell",
        tenant_id="acme",
        env_overrides={"CUSTOM_VAR": "value"},
    )
    assert result["status"] == "running"


async def test_spawn_endpoint_is_valid_k8s_dns() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    endpoint = result["endpoint"]
    assert endpoint.startswith("http://")
    assert ".svc.cluster.local:" in endpoint
    assert result["pod_id"] in endpoint


async def test_reap_then_status_not_found() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    await deployer.reap(result["pod_id"])
    status = await deployer.status(result["pod_id"])
    assert status["status"] == "not_found"


async def test_spawn_preserves_session_id() -> None:
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme", session_id="sess-123")
    status = await deployer.status(result["pod_id"])
    assert status["session_id"] == "sess-123"


# ---------------------------------------------------------------------------
# MCPDeployerClient (real HTTP client) tests using respx
# ---------------------------------------------------------------------------
import httpx  # noqa: E402
import respx  # noqa: E402

from stronghold.sandbox.deployer import MCPDeployerClient  # noqa: E402


async def test_real_client_init_uses_env_default() -> None:
    """Lines 36-37: default base_url from env / fallback."""
    client = MCPDeployerClient()
    assert client._base_url == "http://localhost:8300"
    await client.close()


async def test_real_client_init_custom_url() -> None:
    client = MCPDeployerClient(base_url="http://custom:9000")
    assert client._base_url == "http://custom:9000"
    await client.close()


async def test_real_client_spawn_success() -> None:
    """Lines 54, 64-66: POST /spawn, raise_for_status, return json."""
    async with respx.mock:
        respx.post("http://localhost:8300/spawn").mock(
            return_value=httpx.Response(
                200,
                json={
                    "pod_id": "sandbox-1",
                    "status": "running",
                    "endpoint": "http://sandbox-1.stronghold-mcp.svc.cluster.local:3000",
                },
            )
        )
        client = MCPDeployerClient()
        try:
            result = await client.spawn(
                "sandbox.shell", tenant_id="acme", user_id="alice", session_id="s1"
            )
            assert result["pod_id"] == "sandbox-1"
            assert result["status"] == "running"
        finally:
            await client.close()


async def test_real_client_spawn_http_error() -> None:
    """Line 64: raise_for_status on non-2xx."""
    import pytest

    async with respx.mock:
        respx.post("http://localhost:8300/spawn").mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )
        client = MCPDeployerClient()
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.spawn("sandbox.shell", tenant_id="acme")
        finally:
            await client.close()


async def test_real_client_spawn_with_env_overrides() -> None:
    """Spawn sends env_overrides in the JSON body."""
    import json as _json

    async with respx.mock:
        route = respx.post("http://localhost:8300/spawn").mock(
            return_value=httpx.Response(200, json={"pod_id": "sandbox-2"})
        )
        client = MCPDeployerClient()
        try:
            await client.spawn("sandbox.shell", tenant_id="t", env_overrides={"K": "V"})
            sent = route.calls[0].request
            body = _json.loads(sent.content)
            assert body["env"] == {"K": "V"}
        finally:
            await client.close()


async def test_real_client_reap_success() -> None:
    """Lines 70, 74-77: reap returns True on 200."""
    async with respx.mock:
        respx.post("http://localhost:8300/reap").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        client = MCPDeployerClient()
        try:
            assert await client.reap("sandbox-1") is True
        finally:
            await client.close()


async def test_real_client_reap_not_found() -> None:
    """Line 74-75: reap returns False on 404."""
    async with respx.mock:
        respx.post("http://localhost:8300/reap").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        client = MCPDeployerClient()
        try:
            assert await client.reap("nonexistent") is False
        finally:
            await client.close()


async def test_real_client_reap_server_error() -> None:
    """Lines 76: raise_for_status on 5xx."""
    import pytest

    async with respx.mock:
        respx.post("http://localhost:8300/reap").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        client = MCPDeployerClient()
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.reap("sandbox-1")
        finally:
            await client.close()


async def test_real_client_status_success() -> None:
    """Lines 81-84: GET /status/{pod_id}, raise_for_status, return json."""
    async with respx.mock:
        respx.get("http://localhost:8300/status/sandbox-1").mock(
            return_value=httpx.Response(200, json={"pod_id": "sandbox-1", "status": "running"})
        )
        client = MCPDeployerClient()
        try:
            result = await client.status("sandbox-1")
            assert result["status"] == "running"
        finally:
            await client.close()


async def test_real_client_status_error() -> None:
    """Lines 82: raise_for_status on error."""
    import pytest

    async with respx.mock:
        respx.get("http://localhost:8300/status/bad").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        client = MCPDeployerClient()
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.status("bad")
        finally:
            await client.close()


async def test_real_client_list_active_no_filter() -> None:
    """Lines 88-95: GET /list without tenant filter."""
    async with respx.mock:
        respx.get("http://localhost:8300/list").mock(
            return_value=httpx.Response(200, json={"pods": [{"pod_id": "a"}, {"pod_id": "b"}]})
        )
        client = MCPDeployerClient()
        try:
            pods = await client.list_active()
            assert len(pods) == 2
        finally:
            await client.close()


async def test_real_client_list_active_with_tenant() -> None:
    """Lines 89-90: tenant_id passed as query param."""
    async with respx.mock:
        route = respx.get("http://localhost:8300/list").mock(
            return_value=httpx.Response(200, json={"pods": [{"pod_id": "a"}]})
        )
        client = MCPDeployerClient()
        try:
            pods = await client.list_active(tenant_id="acme")
            assert len(pods) == 1
            request = route.calls[0].request
            assert b"tenant_id=acme" in request.url.raw_path
        finally:
            await client.close()


async def test_real_client_list_active_empty() -> None:
    """Lines 93-95: empty pods list."""
    async with respx.mock:
        respx.get("http://localhost:8300/list").mock(
            return_value=httpx.Response(200, json={"pods": []})
        )
        client = MCPDeployerClient()
        try:
            pods = await client.list_active()
            assert pods == []
        finally:
            await client.close()


async def test_real_client_health_success() -> None:
    """Lines 99-101: health returns True on 200."""
    async with respx.mock:
        respx.get("http://localhost:8300/health").mock(return_value=httpx.Response(200, text="ok"))
        client = MCPDeployerClient()
        try:
            assert await client.health() is True
        finally:
            await client.close()


async def test_real_client_health_non_200() -> None:
    """Lines 99-101: health returns False on non-200."""
    async with respx.mock:
        respx.get("http://localhost:8300/health").mock(
            return_value=httpx.Response(503, text="unavailable")
        )
        client = MCPDeployerClient()
        try:
            assert await client.health() is False
        finally:
            await client.close()


async def test_real_client_health_connection_error() -> None:
    """Lines 102-103: health returns False on exception."""
    async with respx.mock:
        respx.get("http://localhost:8300/health").mock(side_effect=httpx.ConnectError("refused"))
        client = MCPDeployerClient()
        try:
            assert await client.health() is False
        finally:
            await client.close()


async def test_real_client_close() -> None:
    """Line 106: close calls aclose on the underlying client."""
    client = MCPDeployerClient()
    await client.close()
