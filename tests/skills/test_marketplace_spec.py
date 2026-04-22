"""Spec tests for skill marketplace — behavioral tests from specs/skills_marketplace.md.

Covers uncovered lines: 36 (non-IP early-return), 65-67 (urlparse failure),
93-94 (literal-IP public path), 100-101 (DNS gaierror silent return).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from pathlib import Path
from typing import Any

import pytest

from stronghold.skills.marketplace import (
    HTTPResponse,
    SkillMarketplaceImpl,
    _block_ssrf,
    _is_blocked_ip,
)
from stronghold.skills.registry import InMemorySkillRegistry

_VALID_SKILL = """---
name: greeter
description: Greet the user.
groups: [general]
parameters:
  type: object
  properties:
    name:
      type: string
  required:
    - name
endpoint: ""
---

Say hello to the user.
"""

_DANGEROUS_SKILL = """---
name: evil_tool
description: dangerous.
groups: [general]
parameters:
  type: object
  properties:
    cmd:
      type: string
endpoint: ""
---

Execute subprocess.run(cmd)
"""


class _FakeHTTP:
    def __init__(self, response: str = _VALID_SKILL, status: int = 200) -> None:
        self._response = response
        self._status = status
        self.calls: list[str] = []

    async def get(self, url: str) -> HTTPResponse:
        self.calls.append(url)
        return HTTPResponse(self._status, self._response)


class _RaisingHTTP:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[str] = []

    async def get(self, url: str) -> HTTPResponse:
        self.calls.append(url)
        raise self._exc


# ─────────────────── _is_blocked_ip ───────────────────


class TestIsBlockedIP:
    def test_returns_false_for_non_ip_object(self) -> None:
        """Line 36: early-return False when arg is not an IPv4/6Address."""
        assert _is_blocked_ip("not an ip") is False
        assert _is_blocked_ip(None) is False
        assert _is_blocked_ip(12345) is False

    def test_blocks_private_ipv4(self) -> None:
        assert _is_blocked_ip(ipaddress.IPv4Address("10.0.0.1")) is True
        assert _is_blocked_ip(ipaddress.IPv4Address("192.168.1.1")) is True

    def test_blocks_loopback_ipv6(self) -> None:
        assert _is_blocked_ip(ipaddress.IPv6Address("::1")) is True

    def test_permits_public_ipv4(self) -> None:
        assert _is_blocked_ip(ipaddress.IPv4Address("8.8.8.8")) is False


# ─────────────────── _block_ssrf ───────────────────


class TestBlockSSRF:
    def test_rejects_metadata_hostname(self) -> None:
        with pytest.raises(ValueError, match="private/metadata network"):
            _block_ssrf("https://metadata.google.internal/computeMetadata/v1/token")

    def test_rejects_metadata_prefix_also_blocks_example(self) -> None:
        """Known-bug contract: 'metadata.' is a prefix match so
        metadata.example.com is also blocked (false positive).
        Captures current behavior without fixing."""
        with pytest.raises(ValueError, match="private/metadata network"):
            _block_ssrf("https://metadata.example.com/x")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(ValueError, match="private/metadata network"):
            _block_ssrf("http://localhost/x")

    def test_rejects_private_ip_literal(self) -> None:
        with pytest.raises(ValueError, match=r"10\.0\.0\.5"):
            _block_ssrf("http://10.0.0.5/x")

    def test_rejects_ipv6_loopback(self) -> None:
        with pytest.raises(ValueError, match="private/metadata network"):
            _block_ssrf("http://[::1]/x")

    def test_rejects_integer_encoded_private_ip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 2130706433 == 127.0.0.1; ipaddress.ip_address does NOT parse
        # integer strings, so this falls into the DNS-resolve branch —
        # which here resolves to loopback and raises "resolves to private".
        def fake_getaddrinfo(*args, **kwargs):
            return [(0, 0, 0, "", ("127.0.0.1", 0))]
        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(ValueError, match="Blocked"):
            _block_ssrf("http://2130706433/")

    def test_allows_public_ip_literal_without_dns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 93-94: literal public IP returns without calling DNS."""
        calls: list[tuple[Any, ...]] = []

        def spy_getaddrinfo(*args: Any, **kwargs: Any) -> list:
            calls.append(args)
            return []

        monkeypatch.setattr(socket, "getaddrinfo", spy_getaddrinfo)
        _block_ssrf("https://8.8.8.8/x")  # must not raise
        assert calls == []  # DNS not invoked for literal IP

    def test_rejects_dns_rebinding_to_private(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_getaddrinfo(
            host: str, port: Any, family: int, type: int
        ) -> list:
            return [(0, 0, 0, "", ("10.1.2.3", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(ValueError, match="resolves to private/internal"):
            _block_ssrf("https://attacker.example.com/x")

    def test_allows_public_dns_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list:
            return [(0, 0, 0, "", ("8.8.8.8", 0))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        # returns None (no raise)
        assert _block_ssrf("https://ok.example.com/x") is None

    def test_unresolvable_hostname_silently_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 100-101: socket.gaierror → silent return."""

        def boom(*args: Any, **kwargs: Any) -> list:
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", boom)
        # Should not raise (fail at fetch time instead)
        assert _block_ssrf("https://nope.invalid/x") is None

    def test_malformed_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 65-67: urlparse exception → 'malformed URL' ValueError."""

        def boom(url: str) -> Any:
            raise RuntimeError("parse exploded")

        # Patch inside module namespace where it's imported.
        import urllib.parse

        monkeypatch.setattr(urllib.parse, "urlparse", boom)
        with pytest.raises(ValueError, match="malformed URL"):
            _block_ssrf("https://x")




    def test_unparseable_addrinfo_ip_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lines 100-101: if ipaddress.ip_address raises ValueError on an
        entry returned by getaddrinfo, that entry is skipped (continue)."""

        # Return one garbage IP string and one valid public IP.
        def fake_getaddrinfo(*args, **kwargs):
            return [
                (0, 0, 0, "", ("not-an-ip", 0)),
                (0, 0, 0, "", ("8.8.8.8", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        # Must not raise — garbage entry skipped, public IP allowed.
        assert _block_ssrf("https://host.example.com/x") is None


# ─────────────────── search (placeholder) ───────────────────


class TestSearch:
    async def test_search_returns_empty_list(self, tmp_path: Path) -> None:
        mp = SkillMarketplaceImpl(_FakeHTTP(), tmp_path, InMemorySkillRegistry())
        assert await mp.search("anything") == []


# ─────────────────── install ───────────────────


class TestInstall:
    async def test_ssrf_blocked_url_raises_before_http(self, tmp_path: Path) -> None:
        http = _FakeHTTP()
        mp = SkillMarketplaceImpl(http, tmp_path, InMemorySkillRegistry())
        with pytest.raises(ValueError, match="private/metadata network"):
            await mp.install("http://localhost/x")
        assert http.calls == []

    async def test_http_exception_wraps(self, tmp_path: Path) -> None:
        inner = RuntimeError("net down")
        mp = SkillMarketplaceImpl(_RaisingHTTP(inner), tmp_path, InMemorySkillRegistry())
        with pytest.raises(ValueError, match="Failed to fetch skill from") as ei:
            await mp.install("https://example.com/s.md")
        assert ei.value.__cause__ is inner

    async def test_non_200_raises(self, tmp_path: Path) -> None:
        mp = SkillMarketplaceImpl(
            _FakeHTTP(status=404), tmp_path, InMemorySkillRegistry()
        )
        with pytest.raises(ValueError, match="Skill fetch returned 404"):
            await mp.install("https://example.com/x.md")

    async def test_security_scan_rejection(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        mp = SkillMarketplaceImpl(
            _FakeHTTP(_DANGEROUS_SKILL), tmp_path, registry
        )
        with pytest.raises(ValueError, match="rejected by security scan"):
            await mp.install("https://example.com/evil.md")
        assert "evil_tool" not in registry
        assert not (tmp_path / "community" / "evil_tool.md").exists()

    async def test_parse_failure_raises(self, tmp_path: Path) -> None:
        mp = SkillMarketplaceImpl(
            _FakeHTTP("just garbage"), tmp_path, InMemorySkillRegistry()
        )
        with pytest.raises(ValueError, match="Failed to parse skill from"):
            await mp.install("https://example.com/bad.md")

    async def test_happy_path_saves_and_registers_at_default_tier(
        self, tmp_path: Path
    ) -> None:
        registry = InMemorySkillRegistry()
        mp = SkillMarketplaceImpl(_FakeHTTP(), tmp_path, registry)
        url = "https://example.com/greeter.md"
        skill = await mp.install(url)
        assert skill.name == "greeter"
        assert skill.trust_tier == "t2"
        assert skill.source == url
        assert (tmp_path / "community" / "greeter.md").exists()
        assert "greeter" in registry

    async def test_honors_custom_trust_tier(self, tmp_path: Path) -> None:
        mp = SkillMarketplaceImpl(
            _FakeHTTP(), tmp_path, InMemorySkillRegistry()
        )
        skill = await mp.install("https://example.com/x.md", trust_tier="t3")
        assert skill.trust_tier == "t3"

    async def test_creates_community_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "new"
        mp = SkillMarketplaceImpl(_FakeHTTP(), nested, InMemorySkillRegistry())
        await mp.install("https://example.com/greeter.md")
        assert (nested / "community").is_dir()
        assert (nested / "community" / "greeter.md").is_file()

    async def test_info_log_includes_warning_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warnings count includes only findings starting with 'WARNING:'.

        The valid skill's body contains 'curl' (shell_command WARNING-level)
        nowhere — so we craft a body that triggers the external_url warning.
        """
        body_with_warning = _VALID_SKILL.replace(
            "Say hello to the user.",
            "Say hello to the user. See http://foreign-host.example/docs",
        )
        mp = SkillMarketplaceImpl(
            _FakeHTTP(body_with_warning), tmp_path, InMemorySkillRegistry()
        )
        with caplog.at_level(logging.INFO, logger="stronghold.skills.marketplace"):
            await mp.install("https://example.com/greeter.md")
        # At least one INFO log includes the canonical "Installed skill" string
        msgs = [r.message for r in caplog.records]
        assert any(
            "Installed skill 'greeter'" in m and "tier=t2" in m and "warnings=" in m
            for m in msgs
        )


# ─────────────────── uninstall ───────────────────


class TestUninstall:
    def test_missing_raises(self, tmp_path: Path) -> None:
        registry = InMemorySkillRegistry()
        mp = SkillMarketplaceImpl(_FakeHTTP(), tmp_path, registry)
        with pytest.raises(ValueError, match="Community skill 'ghost' not found"):
            mp.uninstall("ghost")

    async def test_removes_file_and_registry_entry(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = InMemorySkillRegistry()
        mp = SkillMarketplaceImpl(_FakeHTTP(), tmp_path, registry)
        await mp.install("https://example.com/greeter.md")
        assert "greeter" in registry
        with caplog.at_level(logging.INFO, logger="stronghold.skills.marketplace"):
            mp.uninstall("greeter")
        assert "greeter" not in registry
        assert not (tmp_path / "community" / "greeter.md").exists()
        assert any("Uninstalled skill: greeter" in r.message for r in caplog.records)
