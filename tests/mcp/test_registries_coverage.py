"""Tests for stronghold.mcp.registries — external registry connectors and scanner.

Covers: RegistryServer, search_smithery, search_official_registry, search_glama,
search_all_registries, scan_registry_server.

HTTP is mocked with ``respx`` (external service, allowed by testing rules), so the
real production function runs unchanged against a real ``httpx.AsyncClient`` — we
only swap the network at the transport layer. This exercises the actual URL
building, header construction, JSON parsing, and error handling in
``stronghold.mcp.registries``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from stronghold.mcp.registries import (
    RegistryServer,
    scan_registry_server,
    search_all_registries,
    search_glama,
    search_official_registry,
    search_smithery,
)
from stronghold.types.security import WardenVerdict

SMITHERY_URL = "https://registry.smithery.ai/servers"
OFFICIAL_URL = "https://registry.modelcontextprotocol.io/api/servers"
GLAMA_URL = "https://glama.ai/api/mcp/servers"


# ── RegistryServer dataclass ──────────────────────────────────────────


class TestRegistryServer:
    def test_to_dict(self) -> None:
        server = RegistryServer(
            name="github-mcp",
            description="GitHub tools",
            author="anthropic",
            registry="smithery",
            repo_url="https://github.com/example",
            homepage="https://example.com",
            verified=True,
            use_count=100,
            image="ghcr.io/test:latest",
            tags=("git", "code"),
            scan_status="clean",
            scan_flags=["low_adoption: <10 uses, unverified"],
        )
        d = server.to_dict()
        assert d["name"] == "github-mcp"
        assert d["description"] == "GitHub tools"
        assert d["author"] == "anthropic"
        assert d["registry"] == "smithery"
        assert d["repo_url"] == "https://github.com/example"
        assert d["homepage"] == "https://example.com"
        assert d["verified"] is True
        assert d["use_count"] == 100
        assert d["image"] == "ghcr.io/test:latest"
        assert d["tags"] == ["git", "code"]
        assert d["scan_status"] == "clean"
        assert d["scan_flags"] == ["low_adoption: <10 uses, unverified"]

    def test_to_dict_empty_tags_tuple(self) -> None:
        server = RegistryServer(name="test")
        d = server.to_dict()
        assert d["tags"] == []


# ── search_smithery ───────────────────────────────────────────────────


class TestSearchSmithery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self) -> None:
        route = respx.get(SMITHERY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "servers": [
                        {
                            "qualifiedName": "anthropic/github-mcp",
                            "displayName": "GitHub MCP",
                            "description": "GitHub integration",
                            "homepage": "https://smithery.ai/server/github-mcp",
                            "verified": True,
                            "useCount": 999,
                        },
                        {
                            "qualifiedName": "fs-server",
                            "description": "Filesystem access",
                            "homepage": "",
                            "verified": False,
                            "useCount": 5,
                        },
                    ]
                },
            )
        )

        results = await search_smithery("github")

        assert route.called
        # Real production code actually hit the URL with our query params.
        sent = route.calls.last.request
        assert sent.url.params["q"] == "github"
        assert sent.url.params["page"] == "1"
        assert sent.url.params["pageSize"] == "10"

        assert len(results) == 2
        assert results[0].name == "anthropic/github-mcp"
        assert results[0].author == "anthropic"
        assert results[0].registry == "smithery"
        assert results[0].verified is True
        assert results[0].use_count == 999
        # Second server has no "/" in qualifiedName so author is ""
        assert results[1].name == "fs-server"
        assert results[1].author == ""

    @pytest.mark.asyncio
    @respx.mock
    async def test_with_api_key(self) -> None:
        route = respx.get(SMITHERY_URL).mock(
            return_value=httpx.Response(200, json={"servers": []})
        )

        results = await search_smithery("test", api_key="sk-test-key")

        assert results == []
        # The real httpx client sent our Authorization header.
        sent = route.calls.last.request
        assert sent.headers["authorization"] == "Bearer sk-test-key"
        assert sent.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_200_status(self) -> None:
        respx.get(SMITHERY_URL).mock(return_value=httpx.Response(500))

        results = await search_smithery("test")

        assert results == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error(self) -> None:
        respx.get(SMITHERY_URL).mock(side_effect=httpx.ConnectError("Connection refused"))

        results = await search_smithery("test")

        assert results == []


# ── search_official_registry ──────────────────────────────────────────


class TestSearchOfficialRegistry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success_dict_response(self) -> None:
        route = respx.get(OFFICIAL_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "servers": [
                        {
                            "name": "github-mcp",
                            "description": "Official GitHub MCP server",
                            "author": "anthropic",
                            "repository": "https://github.com/modelcontextprotocol/servers",
                            "homepage": "https://modelcontextprotocol.io",
                        },
                    ]
                },
            )
        )

        results = await search_official_registry("github")

        assert route.called
        params = route.calls.last.request.url.params
        assert params["q"] == "github"
        # Production sends the page_size as "count" (not "pageSize").
        assert params["count"] == "10"

        assert len(results) == 1
        assert results[0].name == "github-mcp"
        assert results[0].registry == "official"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/modelcontextprotocol/servers"

    @pytest.mark.asyncio
    @respx.mock
    async def test_success_list_response(self) -> None:
        """When API returns a list directly (not wrapped in dict)."""
        respx.get(OFFICIAL_URL).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "github-mcp",
                        "description": "GitHub",
                        "vendor": "anthropic",
                        "repo_url": "https://github.com/test",
                    },
                ],
            )
        )

        results = await search_official_registry("github")

        assert len(results) == 1
        # Uses "id" as fallback when "name" is absent.
        assert results[0].name == "github-mcp"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_200_status(self) -> None:
        respx.get(OFFICIAL_URL).mock(return_value=httpx.Response(403))

        results = await search_official_registry("test")

        assert results == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error(self) -> None:
        respx.get(OFFICIAL_URL).mock(side_effect=httpx.ReadTimeout("Timeout"))

        results = await search_official_registry("test")

        assert results == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_dict_items_skipped(self) -> None:
        """Non-dict items in the servers list should be skipped."""
        respx.get(OFFICIAL_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "servers": [
                        "not-a-dict",
                        {"name": "valid-server", "description": "Valid"},
                    ]
                },
            )
        )

        results = await search_official_registry("test")

        assert len(results) == 1
        assert results[0].name == "valid-server"


# ── search_glama ──────────────────────────────────────────────────────


class TestSearchGlama:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self) -> None:
        route = respx.get(GLAMA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "servers": [
                        {
                            "name": "github-tools",
                            "description": "GitHub MCP tools",
                            "owner": "anthropic",
                            "github_url": "https://github.com/anthropic/github-mcp",
                        },
                    ]
                },
            )
        )

        results = await search_glama("github")

        assert route.called
        params = route.calls.last.request.url.params
        assert params["q"] == "github"
        assert params["limit"] == "10"

        assert len(results) == 1
        assert results[0].name == "github-tools"
        assert results[0].registry == "glama"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/anthropic/github-mcp"
        assert "glama.ai/mcp/servers/anthropic/github-tools" in results[0].homepage

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error(self) -> None:
        respx.get(GLAMA_URL).mock(side_effect=httpx.ConnectError("DNS failed"))

        results = await search_glama("test")

        assert results == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_dict_items_skipped(self) -> None:
        respx.get(GLAMA_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "servers": [
                        "string-item",
                        {"name": "valid", "description": "Valid server"},
                    ]
                },
            )
        )

        results = await search_glama("test")

        assert len(results) == 1
        assert results[0].name == "valid"

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_response_format(self) -> None:
        """When API returns a bare list."""
        respx.get(GLAMA_URL).mock(
            return_value=httpx.Response(
                200,
                json=[{"name": "bare-list-server", "description": "A server"}],
            )
        )

        results = await search_glama("test")

        assert len(results) == 1
        assert results[0].name == "bare-list-server"


# ── search_all_registries ────────────────────────────────────────────
#
# These tests exercise the real ``search_all_registries`` coordinator, which
# calls the real ``search_smithery`` / ``search_official_registry`` /
# ``search_glama`` functions via ``asyncio.gather``. We let all three run
# for real, intercepting the three distinct URLs at the HTTP layer — this
# proves the coordinator's error isolation (one registry failing does not
# take down the others) rather than faking the coordinator's inputs.


class TestSearchAllRegistries:
    @pytest.mark.asyncio
    @respx.mock
    async def test_all_succeed(self) -> None:
        """All three registries return results through the real aggregator."""
        respx.get(SMITHERY_URL).mock(
            return_value=httpx.Response(
                200,
                json={"servers": [{"qualifiedName": "anthropic/smithery-server"}]},
            )
        )
        respx.get(OFFICIAL_URL).mock(
            return_value=httpx.Response(
                200, json={"servers": [{"name": "official-server"}]}
            )
        )
        respx.get(GLAMA_URL).mock(
            return_value=httpx.Response(
                200, json={"servers": [{"name": "glama-server"}]}
            )
        )

        results = await search_all_registries("test")

        assert "smithery" in results
        assert "official" in results
        assert "glama" in results
        assert len(results["smithery"]) == 1
        assert results["smithery"][0].registry == "smithery"
        assert len(results["official"]) == 1
        assert results["official"][0].registry == "official"
        assert len(results["glama"]) == 1
        assert results["glama"][0].registry == "glama"

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_registry_fails(self) -> None:
        """When one registry fails, others still return (real resilience test)."""
        # Smithery network-errors at the transport layer.
        respx.get(SMITHERY_URL).mock(side_effect=httpx.ConnectError("Smithery is down"))
        respx.get(OFFICIAL_URL).mock(
            return_value=httpx.Response(
                200, json={"servers": [{"name": "official-server"}]}
            )
        )
        respx.get(GLAMA_URL).mock(
            return_value=httpx.Response(
                200, json={"servers": [{"name": "glama-server"}]}
            )
        )

        results = await search_all_registries("test")

        assert results["smithery"] == []
        assert len(results["official"]) == 1
        assert len(results["glama"]) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_fail(self) -> None:
        respx.get(SMITHERY_URL).mock(side_effect=httpx.ConnectError("Down"))
        respx.get(OFFICIAL_URL).mock(side_effect=httpx.ConnectError("Down"))
        respx.get(GLAMA_URL).mock(side_effect=httpx.ConnectError("Down"))

        results = await search_all_registries("test")

        assert results["smithery"] == []
        assert results["official"] == []
        assert results["glama"] == []


# ── scan_registry_server ──────────────────────────────────────────────
#
# The scanner is a pure heuristic / Warden invocation — no HTTP. These tests
# already exercise the real production path; preserved verbatim.


class TestScanRegistryServer:
    @pytest.mark.asyncio
    async def test_clean_server(self) -> None:
        server = RegistryServer(
            name="safe-server",
            description="A safe MCP server for file operations",
            author="anthropic",
            verified=True,
            use_count=500,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "clean"
        assert result.scan_flags == []

    @pytest.mark.asyncio
    async def test_suspicious_description_bypass(self) -> None:
        server = RegistryServer(
            name="normal-server",
            description="This server can bypass all restrictions",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"
        assert any("bypass" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_suspicious_description_shell_access(self) -> None:
        server = RegistryServer(
            name="normal-server",
            description="Provides shell access to the system",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"
        assert any("shell access" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_suspicious_name(self) -> None:
        server = RegistryServer(
            name="bypass-all-restrictions",
            description="Normal tools",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"

    @pytest.mark.asyncio
    async def test_low_adoption(self) -> None:
        server = RegistryServer(
            name="new-server",
            description="A brand new server",
            verified=False,
            use_count=5,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"
        assert any("low_adoption" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_low_adoption_not_flagged_when_verified(self) -> None:
        server = RegistryServer(
            name="new-server",
            description="A brand new server",
            verified=True,
            use_count=5,
        )
        result = await scan_registry_server(server)
        assert not any("low_adoption" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_suspicious_author(self) -> None:
        server = RegistryServer(
            name="normal-tool",
            description="Normal description",
            author="h4ck3r-exploit",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"
        assert any("suspicious_author" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_multiple_flags(self) -> None:
        server = RegistryServer(
            name="bypass-server",
            description="Execute any command with no limits and unrestricted access",
            author="crack-team",
            verified=False,
            use_count=2,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "flagged"
        assert len(result.scan_flags) >= 3

    @pytest.mark.asyncio
    async def test_warden_scan_blocks(self) -> None:
        """When Warden flags content, scan_status should be 'blocked'."""

        class BlockingWarden:
            async def scan(self, content: str, boundary: str) -> WardenVerdict:
                return WardenVerdict(clean=False, flags=("injection",), confidence=0.9)

        server = RegistryServer(
            name="safe-looking",
            description="Totally normal server",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server, warden=BlockingWarden())
        assert result.scan_status == "blocked"
        assert any("warden:" in f for f in result.scan_flags)

    @pytest.mark.asyncio
    async def test_warden_scan_clean(self) -> None:
        """When Warden passes, and no heuristic flags, status is 'clean'."""

        class CleanWarden:
            async def scan(self, content: str, boundary: str) -> WardenVerdict:
                return WardenVerdict(clean=True, flags=(), confidence=1.0)

        server = RegistryServer(
            name="safe-server",
            description="Totally normal server",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server, warden=CleanWarden())
        assert result.scan_status == "clean"
        assert result.scan_flags == []

    @pytest.mark.asyncio
    async def test_no_warden_no_description(self) -> None:
        """No warden, no description to scan = clean."""
        server = RegistryServer(
            name="minimal",
            verified=True,
            use_count=100,
        )
        result = await scan_registry_server(server)
        assert result.scan_status == "clean"

    @pytest.mark.asyncio
    async def test_warden_not_called_when_no_description(self) -> None:
        """Warden should not be called when description is empty."""
        call_count = 0

        class TrackingWarden:
            async def scan(self, content: str, boundary: str) -> WardenVerdict:
                nonlocal call_count
                call_count += 1
                return WardenVerdict(clean=True, flags=(), confidence=1.0)

        server = RegistryServer(
            name="no-desc",
            description="",
            verified=True,
            use_count=100,
        )
        await scan_registry_server(server, warden=TrackingWarden())
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_all_suspicious_patterns_detected(self) -> None:
        """Each suspicious pattern in the list should be detectable."""
        suspicious_patterns = [
            "unrestricted",
            "no restrictions",
            "bypass",
            "override",
            "full access",
            "admin mode",
            "shell access",
            "execute any",
            "unlimited",
            "no limits",
            "ignore safety",
            "developer mode",
        ]
        for pattern in suspicious_patterns:
            server = RegistryServer(
                name="test-server",
                description=f"This server provides {pattern} functionality",
                verified=True,
                use_count=100,
            )
            result = await scan_registry_server(server)
            assert result.scan_status == "flagged", f"Pattern '{pattern}' not detected"
            assert any(pattern in f for f in result.scan_flags), (
                f"Pattern '{pattern}' not in flags"
            )
