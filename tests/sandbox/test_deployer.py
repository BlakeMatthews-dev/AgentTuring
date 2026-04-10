"""Tests for MCPDeployerClient (ADR-K8S-025/026)."""

from __future__ import annotations

from stronghold.sandbox.deployer import FakeMCPDeployerClient


async def test_spawn_unique_ids_basic() -> None:
    deployer = FakeMCPDeployerClient()
    r1 = await deployer.spawn("sandbox.shell", tenant_id="acme")
    r2 = await deployer.spawn("sandbox.python", tenant_id="acme")
    assert r1["pod_id"] != r2["pod_id"]


async def test_reap_nonexistent_pod() -> None:
    deployer = FakeMCPDeployerClient()
    assert await deployer.reap("nonexistent") is False


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


async def test_reap_removes_pod_from_list() -> None:
    """Reap must actually remove the pod from active list."""
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn("sandbox.shell", tenant_id="acme")
    pod_id = result["pod_id"]
    assert len(await deployer.list_active()) == 1
    assert await deployer.reap(pod_id) is True
    assert len(await deployer.list_active()) == 0
    # Second reap of same pod should return False (already gone)
    assert await deployer.reap(pod_id) is False


async def test_spawn_stores_all_fields_distinctly() -> None:
    """Every field in spawn params must be retrievable — not hardcoded."""
    deployer = FakeMCPDeployerClient()
    result = await deployer.spawn(
        "sandbox.python",  # NOT sandbox.shell
        tenant_id="zeta-corp",  # NOT acme
        user_id="charlie",  # NOT alice
        session_id="s-xyz-999",
    )
    assert result["template"] == "sandbox.python"
    assert result["tenant_id"] == "zeta-corp"
    assert result["user_id"] == "charlie"
    assert result["session_id"] == "s-xyz-999"


async def test_spawn_100_ids_all_unique() -> None:
    """Pod IDs must be unique across many calls, not just 2."""
    deployer = FakeMCPDeployerClient()
    ids = []
    for _ in range(100):
        r = await deployer.spawn("sandbox.shell", tenant_id="acme")
        ids.append(r["pod_id"])
    assert len(set(ids)) == 100


async def test_list_active_contains_spawned_ids() -> None:
    """list_active must contain the actual spawned pod ids."""
    deployer = FakeMCPDeployerClient()
    r1 = await deployer.spawn("sandbox.shell", tenant_id="acme")
    r2 = await deployer.spawn("sandbox.python", tenant_id="acme")
    pods = await deployer.list_active()
    ids = {p["pod_id"] for p in pods}
    assert r1["pod_id"] in ids
    assert r2["pod_id"] in ids


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


# ── Real MCPDeployerClient HTTP tests (respx-mocked) ────────────────

import respx
import httpx

from stronghold.sandbox.deployer import MCPDeployerClient


@respx.mock
async def test_real_client_spawn_posts_correct_payload() -> None:
    """Real client must POST to /spawn with exact payload shape."""
    route = respx.post("http://localhost:8300/spawn").mock(
        return_value=httpx.Response(200, json={
            "pod_id": "sandbox-abc",
            "status": "running",
            "endpoint": "http://sandbox-abc.stronghold-mcp.svc.cluster.local:3000",
        }),
    )
    client = MCPDeployerClient()
    result = await client.spawn(
        "sandbox.python", tenant_id="acme", user_id="alice",
        session_id="s-1", env_overrides={"X": "y"},
    )
    assert route.called
    sent = route.calls.last.request
    import json as _json
    body = _json.loads(sent.content)
    assert body["template"] == "sandbox.python"
    assert body["tenant_id"] == "acme"
    assert body["user_id"] == "alice"
    assert body["session_id"] == "s-1"
    assert body["env"] == {"X": "y"}
    assert result["pod_id"] == "sandbox-abc"
    await client.close()


@respx.mock
async def test_real_client_reap_uses_post() -> None:
    """Real client must POST to /reap with pod_id."""
    route = respx.post("http://localhost:8300/reap").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )
    client = MCPDeployerClient()
    result = await client.reap("sandbox-abc")
    assert route.called
    assert result is True
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    assert body == {"pod_id": "sandbox-abc"}
    await client.close()


@respx.mock
async def test_real_client_reap_404_returns_false() -> None:
    respx.post("http://localhost:8300/reap").mock(
        return_value=httpx.Response(404),
    )
    client = MCPDeployerClient()
    assert await client.reap("missing") is False
    await client.close()


@respx.mock
async def test_real_client_status_uses_get_with_path() -> None:
    respx.get("http://localhost:8300/status/sandbox-abc").mock(
        return_value=httpx.Response(200, json={"status": "running", "pod_id": "sandbox-abc"}),
    )
    client = MCPDeployerClient()
    result = await client.status("sandbox-abc")
    assert result["status"] == "running"
    await client.close()


@respx.mock
async def test_real_client_health_ok() -> None:
    respx.get("http://localhost:8300/health").mock(return_value=httpx.Response(200))
    client = MCPDeployerClient()
    assert await client.health() is True
    await client.close()


@respx.mock
async def test_real_client_health_500() -> None:
    respx.get("http://localhost:8300/health").mock(return_value=httpx.Response(500))
    client = MCPDeployerClient()
    assert await client.health() is False
    await client.close()


@respx.mock
async def test_real_client_health_network_error() -> None:
    respx.get("http://localhost:8300/health").mock(
        side_effect=httpx.ConnectError("refused"),
    )
    client = MCPDeployerClient()
    assert await client.health() is False
    await client.close()


@respx.mock
async def test_real_client_list_active_passes_tenant_filter() -> None:
    route = respx.get("http://localhost:8300/list").mock(
        return_value=httpx.Response(200, json={"pods": [{"pod_id": "p1", "tenant_id": "acme"}]}),
    )
    client = MCPDeployerClient()
    result = await client.list_active(tenant_id="acme")
    assert route.called
    assert route.calls.last.request.url.params["tenant_id"] == "acme"
    assert len(result) == 1
    await client.close()
