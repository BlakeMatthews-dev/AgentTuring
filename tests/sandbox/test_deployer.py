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
        "sandbox.shell", tenant_id="acme",
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
