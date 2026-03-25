"""Tests for stronghold.mcp.registries — external registry connectors and scanner.

Covers: RegistryServer, search_smithery, search_official_registry, search_glama,
search_all_registries, scan_registry_server.

External HTTP calls are mocked (httpx). Warden scanning uses the real Warden class.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stronghold.mcp.registries import (
    RegistryServer,
    scan_registry_server,
    search_all_registries,
    search_glama,
    search_official_registry,
    search_smithery,
)
from stronghold.security.warden.detector import Warden
from stronghold.types.security import WardenVerdict


# ── RegistryServer dataclass ──────────────────────────────────────────


class TestRegistryServer:
    def test_default_fields(self) -> None:
        server = RegistryServer(name="test-server")
        assert server.name == "test-server"
        assert server.description == ""
        assert server.author == ""
        assert server.registry == ""
        assert server.repo_url == ""
        assert server.homepage == ""
        assert server.verified is False
        assert server.use_count == 0
        assert server.image == ""
        assert server.tags == ()
        assert server.scan_status == "unscanned"
        assert server.scan_flags == []

    def test_full_fields(self) -> None:
        server = RegistryServer(
            name="github-mcp",
            description="GitHub integration",
            author="anthropic",
            registry="smithery",
            repo_url="https://github.com/anthropic/mcp-server-github",
            homepage="https://smithery.ai/server/github-mcp",
            verified=True,
            use_count=500,
            image="ghcr.io/modelcontextprotocol/server-github:latest",
            tags=("git", "code"),
            scan_status="clean",
            scan_flags=[],
        )
        assert server.verified is True
        assert server.use_count == 500

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
    async def test_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_smithery("github")

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
    async def test_with_api_key(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"servers": []}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_smithery("test", api_key="sk-test-key")

        assert results == []
        # Verify headers included the API key
        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("Authorization") == "Bearer sk-test-key"

    @pytest.mark.asyncio
    async def test_non_200_status(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_smithery("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_smithery("test")

        assert results == []


# ── search_official_registry ──────────────────────────────────────────


class TestSearchOfficialRegistry:
    @pytest.mark.asyncio
    async def test_success_dict_response(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                {
                    "name": "github-mcp",
                    "description": "Official GitHub MCP server",
                    "author": "anthropic",
                    "repository": "https://github.com/modelcontextprotocol/servers",
                    "homepage": "https://modelcontextprotocol.io",
                },
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_official_registry("github")

        assert len(results) == 1
        assert results[0].name == "github-mcp"
        assert results[0].registry == "official"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/modelcontextprotocol/servers"

    @pytest.mark.asyncio
    async def test_success_list_response(self) -> None:
        """When API returns a list directly (not wrapped in dict)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "github-mcp",
                "description": "GitHub",
                "vendor": "anthropic",
                "repo_url": "https://github.com/test",
            },
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_official_registry("github")

        assert len(results) == 1
        # Uses "id" as fallback when "name" is absent
        assert results[0].name == "github-mcp"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/test"

    @pytest.mark.asyncio
    async def test_non_200_status(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_official_registry("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_official_registry("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_non_dict_items_skipped(self) -> None:
        """Non-dict items in the servers list should be skipped."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                "not-a-dict",
                {"name": "valid-server", "description": "Valid"},
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_official_registry("test")

        assert len(results) == 1
        assert results[0].name == "valid-server"


# ── search_glama ──────────────────────────────────────────────────────


class TestSearchGlama:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                {
                    "name": "github-tools",
                    "description": "GitHub MCP tools",
                    "owner": "anthropic",
                    "github_url": "https://github.com/anthropic/github-mcp",
                },
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_glama("github")

        assert len(results) == 1
        assert results[0].name == "github-tools"
        assert results[0].registry == "glama"
        assert results[0].author == "anthropic"
        assert results[0].repo_url == "https://github.com/anthropic/github-mcp"
        assert "glama.ai/mcp/servers/anthropic/github-tools" in results[0].homepage

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("DNS failed")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_glama("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_non_dict_items_skipped(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "servers": [
                "string-item",
                {"name": "valid", "description": "Valid server"},
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_glama("test")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_response_format(self) -> None:
        """When API returns a bare list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "bare-list-server", "description": "A server"}
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("stronghold.mcp.registries.httpx.AsyncClient", return_value=mock_client):
            results = await search_glama("test")

        assert len(results) == 1
        assert results[0].name == "bare-list-server"


# ── search_all_registries ────────────────────────────────────────────


class TestSearchAllRegistries:
    @pytest.mark.asyncio
    async def test_all_succeed(self) -> None:
        """All three registries return results."""

        async def fake_smithery(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="smithery-server", registry="smithery")]

        async def fake_official(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="official-server", registry="official")]

        async def fake_glama(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="glama-server", registry="glama")]

        with (
            patch("stronghold.mcp.registries.search_smithery", fake_smithery),
            patch("stronghold.mcp.registries.search_official_registry", fake_official),
            patch("stronghold.mcp.registries.search_glama", fake_glama),
        ):
            results = await search_all_registries("test")

        assert "smithery" in results
        assert "official" in results
        assert "glama" in results
        assert len(results["smithery"]) == 1
        assert len(results["official"]) == 1
        assert len(results["glama"]) == 1

    @pytest.mark.asyncio
    async def test_one_registry_fails(self) -> None:
        """When one registry raises an exception, others still return."""

        async def fake_smithery(query: str, **kw: Any) -> list[RegistryServer]:
            raise RuntimeError("Smithery is down")

        async def fake_official(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="official-server")]

        async def fake_glama(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="glama-server")]

        with (
            patch("stronghold.mcp.registries.search_smithery", fake_smithery),
            patch("stronghold.mcp.registries.search_official_registry", fake_official),
            patch("stronghold.mcp.registries.search_glama", fake_glama),
        ):
            results = await search_all_registries("test")

        # Smithery failed, should be empty list
        assert results["smithery"] == []
        assert len(results["official"]) == 1
        assert len(results["glama"]) == 1

    @pytest.mark.asyncio
    async def test_all_fail(self) -> None:
        async def fail(query: str, **kw: Any) -> list[RegistryServer]:
            raise RuntimeError("Down")

        with (
            patch("stronghold.mcp.registries.search_smithery", fail),
            patch("stronghold.mcp.registries.search_official_registry", fail),
            patch("stronghold.mcp.registries.search_glama", fail),
        ):
            results = await search_all_registries("test")

        assert results["smithery"] == []
        assert results["official"] == []
        assert results["glama"] == []


# ── scan_registry_server ──────────────────────────────────────────────


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
        # Verified servers with low use count should not be flagged for low_adoption
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
            "unrestricted", "no restrictions", "bypass", "override", "full access",
            "admin mode", "shell access", "execute any", "unlimited", "no limits",
            "ignore safety", "developer mode",
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
            assert any(pattern in f for f in result.scan_flags), f"Pattern '{pattern}' not in flags"
