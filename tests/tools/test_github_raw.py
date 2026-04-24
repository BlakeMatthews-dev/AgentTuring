"""github_raw escape-hatch tool: allowlist + proxy + error handling."""

from __future__ import annotations

import httpx
import respx

from stronghold.tools.github_raw import GITHUB_RAW_TOOL_DEF, GitHubRawExecutor


async def test_tool_definition_declares_expected_fields() -> None:
    assert GITHUB_RAW_TOOL_DEF.name == "github_raw"
    props = GITHUB_RAW_TOOL_DEF.parameters["properties"]
    assert set(props) == {"method", "endpoint", "params", "body_json"}
    assert GITHUB_RAW_TOOL_DEF.parameters["required"] == ["method", "endpoint"]
    assert set(props["method"]["enum"]) == {"GET", "POST", "PATCH", "PUT", "DELETE"}


async def test_rejects_disallowed_method() -> None:
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "OPTIONS", "endpoint": "/repos/a/b"})
    assert result.success is False
    assert result.error is not None
    assert "not allowed" in result.error


async def test_rejects_endpoint_without_leading_slash() -> None:
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "GET", "endpoint": "repos/a/b"})
    assert result.success is False
    assert result.error is not None
    assert "must start with" in result.error


async def test_rejects_denylisted_paths() -> None:
    executor = GitHubRawExecutor()
    for denied in ("/admin/users", "/enterprise/settings", "/scim/Users", "/app/installations"):
        result = await executor.execute({"method": "GET", "endpoint": denied})
        assert result.success is False, f"expected denial for {denied}"
        assert "denied" in (result.error or "")


async def test_rejects_paths_outside_allowlist() -> None:
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "GET", "endpoint": "/unknown/area"})
    assert result.success is False
    assert "allowlisted" in (result.error or "")


@respx.mock
async def test_get_proxies_and_returns_json() -> None:
    respx.mock.get("https://api.github.com/repos/acme/widget").mock(
        return_value=httpx.Response(200, json={"name": "widget", "stars": 42}),
    )
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "GET", "endpoint": "/repos/acme/widget"})
    assert result.success is True
    assert '"stars": 42' in result.content


@respx.mock
async def test_post_sends_body_json() -> None:
    route = respx.mock.post("https://api.github.com/repos/acme/widget/issues").mock(
        return_value=httpx.Response(201, json={"number": 1, "title": "x"}),
    )
    executor = GitHubRawExecutor()
    result = await executor.execute(
        {
            "method": "POST",
            "endpoint": "/repos/acme/widget/issues",
            "body_json": {"title": "x", "body": "details"},
        }
    )
    assert result.success is True
    assert route.called
    import json  # noqa: PLC0415

    sent = json.loads(route.calls[0].request.content)
    assert sent == {"title": "x", "body": "details"}


@respx.mock
async def test_upstream_4xx_surfaces_as_failure() -> None:
    respx.mock.get("https://api.github.com/repos/acme/nope").mock(
        return_value=httpx.Response(404, text='{"message": "Not Found"}'),
    )
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "GET", "endpoint": "/repos/acme/nope"})
    assert result.success is False
    assert "404" in (result.error or "")


@respx.mock
async def test_non_json_response_returned_as_text() -> None:
    respx.mock.get("https://api.github.com/repos/acme/widget/tarball/main").mock(
        return_value=httpx.Response(
            200,
            text="binary-ish content",
            headers={"content-type": "application/gzip"},
        ),
    )
    executor = GitHubRawExecutor()
    result = await executor.execute(
        {"method": "GET", "endpoint": "/repos/acme/widget/tarball/main"},
    )
    assert result.success is True
    assert result.content == "binary-ish content"


async def test_endpoint_denylist_takes_priority_over_allowlist() -> None:
    """Even if /app/ happened to match some allowlisted prefix, deny wins."""
    executor = GitHubRawExecutor()
    result = await executor.execute({"method": "GET", "endpoint": "/app/installations/123"})
    assert result.success is False
    assert "denied" in (result.error or "")
