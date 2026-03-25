"""Tests for skill marketplace: install, uninstall, security scan."""

from pathlib import Path

import pytest

from stronghold.skills.marketplace import HTTPResponse, SkillMarketplaceImpl, _block_ssrf
from stronghold.skills.registry import InMemorySkillRegistry

_VALID_SKILL = """---
name: community_tool
description: A community-contributed tool.
groups: [general]
parameters:
  type: object
  properties:
    input:
      type: string
  required:
    - input
endpoint: ""
---

Instructions for using this community tool.
"""

_DANGEROUS_SKILL = """---
name: evil_tool
description: A dangerous tool.
groups: [general]
parameters:
  type: object
  properties:
    cmd:
      type: string
endpoint: ""
---

Run exec(cmd) to execute the command.
"""


class FakeHTTPClient:
    """Fake HTTP client that returns canned responses."""

    def __init__(self, response: str = _VALID_SKILL, status_code: int = 200) -> None:
        self._response = response
        self._status_code = status_code

    async def get(self, url: str) -> HTTPResponse:
        return HTTPResponse(self._status_code, self._response)


class FailingHTTPClient:
    async def get(self, url: str) -> HTTPResponse:
        msg = "Connection refused"
        raise ConnectionError(msg)


class TestInstall:
    @pytest.mark.asyncio
    async def test_installs_valid_skill(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FakeHTTPClient(), tmp_path, registry)
        skill = await marketplace.install("https://example.com/skill.md")
        assert skill.name == "community_tool"
        assert skill.trust_tier == "t2"
        assert "community_tool" in registry
        assert (tmp_path / "community" / "community_tool.md").exists()

    @pytest.mark.asyncio
    async def test_custom_trust_tier(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FakeHTTPClient(), tmp_path, registry)
        skill = await marketplace.install("https://example.com/skill.md", trust_tier="t1")
        assert skill.trust_tier == "t1"

    @pytest.mark.asyncio
    async def test_rejects_dangerous_skill(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(
            FakeHTTPClient(_DANGEROUS_SKILL),
            tmp_path,
            registry,
        )
        with pytest.raises(ValueError, match="security scan"):
            await marketplace.install("https://example.com/evil.md")
        assert "evil_tool" not in registry

    @pytest.mark.asyncio
    async def test_fetch_failure_raises(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FailingHTTPClient(), tmp_path, registry)
        with pytest.raises(ValueError, match="Failed to fetch"):
            await marketplace.install("https://example.com/skill.md")

    @pytest.mark.asyncio
    async def test_404_raises(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(
            FakeHTTPClient(status_code=404),
            tmp_path,
            registry,
        )
        with pytest.raises(ValueError, match="404"):
            await marketplace.install("https://example.com/missing.md")

    @pytest.mark.asyncio
    async def test_invalid_content_raises(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(
            FakeHTTPClient("not a skill"),
            tmp_path,
            registry,
        )
        with pytest.raises(ValueError, match="Failed to parse"):
            await marketplace.install("https://example.com/bad.md")


class TestUninstall:
    @pytest.mark.asyncio
    async def test_uninstalls_skill(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FakeHTTPClient(), tmp_path, registry)
        await marketplace.install("https://example.com/skill.md")
        assert "community_tool" in registry

        marketplace.uninstall("community_tool")
        assert "community_tool" not in registry
        assert not (tmp_path / "community" / "community_tool.md").exists()

    def test_uninstall_nonexistent_raises(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FakeHTTPClient(), tmp_path, registry)
        with pytest.raises(ValueError, match="not found"):
            marketplace.uninstall("nonexistent")


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_empty(self, tmp_path: Path) -> None:
        """Search is a placeholder — returns empty until marketplace API is configured."""
        registry = InMemorySkillRegistry()
        marketplace = SkillMarketplaceImpl(FakeHTTPClient(), tmp_path, registry)
        results = await marketplace.search("weather")
        assert results == []


class TestSSRFProtection:
    """Regression tests for SSRF blocklist bypass via alternative IP encodings."""

    def test_blocks_decimal_private_ip(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_blocks_hex_encoded_ip(self) -> None:
        with pytest.raises(ValueError, match="Blocked"):
            _block_ssrf("http://0xa9.0xfe.0xa9.0xfe/latest/meta-data/")

    def test_blocks_loopback_hex(self) -> None:
        with pytest.raises(ValueError, match="Blocked"):
            _block_ssrf("http://0x7f.0.0.1/")

    def test_blocks_ipv6_loopback(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://[::1]/")

    def test_blocks_localhost_hostname(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://localhost/admin")

    def test_blocks_metadata_hostname(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://metadata.google.internal/")

    def test_allows_public_ip(self) -> None:
        _block_ssrf("https://1.2.3.4/api")  # Should not raise

    def test_allows_public_domain(self) -> None:
        _block_ssrf("https://github.com/repo/skill.md")  # Should not raise

    def test_blocks_private_class_a(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://10.0.0.1/internal")

    def test_blocks_private_class_c(self) -> None:
        with pytest.raises(ValueError, match="private/metadata"):
            _block_ssrf("http://192.168.1.1/admin")
