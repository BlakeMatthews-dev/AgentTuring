"""Tests for ResourceCatalog (ADR-K8S-023)."""

from __future__ import annotations

from stronghold.resources.catalog import ResourceCatalog, ResourceEntry, ResolvedResource


async def _mock_resolver(path: str, credentials: dict[str, str]) -> str:
    token = credentials.get("github_token", "none")
    return f'{{"path": "{path}", "token": "{token}"}}'


async def _failing_resolver(path: str, credentials: dict[str, str]) -> str:
    raise RuntimeError("resolver crashed")


async def test_register_and_resolve_global() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(
            uri_template="stronghold://global/system/health",
            description="System health",
            scope="global",
        ),
        _mock_resolver,
    )
    result = await cat.resolve("stronghold://global/system/health")
    assert result is not None
    assert '"path": "system/health"' in result.content


async def test_resolve_with_credentials() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(
            uri_template="stronghold://user/{user_id}/github/repos",
            description="User GitHub repos",
            scope="user",
        ),
        _mock_resolver,
    )
    result = await cat.resolve(
        "stronghold://user/alice/github/repos",
        user_id="alice",
        credentials={"github_token": "ghp_abc123"},
    )
    assert result is not None
    assert '"token": "ghp_abc123"' in result.content


async def test_resolve_invalid_uri() -> None:
    cat = ResourceCatalog()
    result = await cat.resolve("https://example.com")
    assert result is None


async def test_resolve_no_resolver() -> None:
    cat = ResourceCatalog()
    result = await cat.resolve("stronghold://global/unknown/thing")
    assert result is None


async def test_user_namespace_isolation() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(
            uri_template="stronghold://user/{user_id}/secrets",
            scope="user",
        ),
        _mock_resolver,
    )
    # Alice can access her own path
    result = await cat.resolve("stronghold://user/alice/secrets", user_id="alice")
    assert result is not None

    # Bob cannot access Alice's path
    result = await cat.resolve("stronghold://user/alice/secrets", user_id="bob")
    assert result is None

    # No user_id = denied
    result = await cat.resolve("stronghold://user/alice/secrets")
    assert result is None


async def test_tenant_namespace_isolation() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(
            uri_template="stronghold://tenant/{tenant_id}/config",
            scope="tenant",
        ),
        _mock_resolver,
    )
    result = await cat.resolve("stronghold://tenant/acme/config", tenant_id="acme")
    assert result is not None

    result = await cat.resolve("stronghold://tenant/acme/config", tenant_id="evil-corp")
    assert result is None


async def test_list_resources() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(uri_template="stronghold://global/health", scope="global"),
        _mock_resolver,
    )
    cat.register(
        ResourceEntry(uri_template="stronghold://user/{user_id}/keys", scope="user"),
        _mock_resolver,
    )
    cat.register(
        ResourceEntry(uri_template="stronghold://tenant/{tenant_id}/config", scope="tenant"),
        _mock_resolver,
    )

    # Global only
    results = cat.list_resources()
    assert len(results) == 1

    # With user
    results = cat.list_resources(user_id="alice")
    assert len(results) == 2

    # With tenant + user
    results = cat.list_resources(tenant_id="acme", user_id="alice")
    assert len(results) == 3


async def test_resolver_failure_returns_none() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(uri_template="stronghold://global/broken", scope="global"),
        _failing_resolver,
    )
    result = await cat.resolve("stronghold://global/broken")
    assert result is None


async def test_mime_type_preserved() -> None:
    cat = ResourceCatalog()
    cat.register(
        ResourceEntry(
            uri_template="stronghold://global/docs",
            scope="global",
            mime_type="text/markdown",
        ),
        _mock_resolver,
    )
    result = await cat.resolve("stronghold://global/docs")
    assert result is not None
    assert result.mime_type == "text/markdown"
