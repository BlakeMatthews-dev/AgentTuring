"""Skill marketplace: search, install, uninstall community skills.

Fetches SKILL.md files from URLs (GitHub, HTTP endpoints, etc.),
runs security scanning, and installs to the community directory
with T2 trust tier by default.

Uses an injectable HTTP client protocol for testability.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from stronghold.skills.parser import parse_skill_file, security_scan
from stronghold.types.skill import SkillDefinition, SkillMetadata

if TYPE_CHECKING:
    from stronghold.skills.registry import InMemorySkillRegistry

logger = logging.getLogger("stronghold.skills.marketplace")

# Hostname-based blocks (not IP-parseable — e.g. "metadata.google.internal")
_BLOCKED_HOSTNAME_PREFIXES = (
    "metadata.",  # GCP metadata service
    "localhost",  # Loopback
)


def _is_blocked_ip(addr: object) -> bool:
    """Check if an IP address object targets a private/internal network."""
    import ipaddress  # noqa: PLC0415

    if not isinstance(addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return False
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _block_ssrf(url: str) -> None:
    """Block server-side request forgery via private/metadata URLs.

    Uses ipaddress module to correctly handle hex, octal, integer, and
    IPv6-mapped representations — not just decimal prefixes.

    Also resolves hostnames via DNS to defeat rebinding attacks where a
    hostname initially resolves to a public IP but later resolves to an
    internal one.
    """
    import ipaddress  # noqa: PLC0415
    import socket  # noqa: PLC0415
    from urllib.parse import urlparse  # noqa: PLC0415

    url_lower = url.lower()

    # 1. Parse hostname
    try:
        parsed = urlparse(url_lower)
    except Exception:
        msg = f"Blocked: malformed URL: {url}"
        raise ValueError(msg) from None

    hostname = parsed.hostname or ""

    # 2. Hostname-based blocks (non-IP names)
    for prefix in _BLOCKED_HOSTNAME_PREFIXES:
        if hostname.startswith(prefix) or hostname == prefix:
            msg = f"Blocked: URL targets private/metadata network: {url}"
            raise ValueError(msg)

    # 3. IP-based blocks: parse all representations (decimal, hex, octal, integer, IPv6)
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None

    if addr is not None:
        if _is_blocked_ip(addr):
            msg = f"Blocked: URL targets private/metadata network ({addr}): {url}"
            raise ValueError(msg)
        return  # Literal IP that passed checks — no DNS resolution needed

    # 4. DNS rebinding protection: resolve hostname and check all returned IPs.
    # A hostname may resolve to an internal IP even if the name looks benign.
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return  # Unresolvable hostname — will fail at fetch time anyway

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            resolved_addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(resolved_addr):
            msg = (
                f"Blocked: hostname '{hostname}' resolves to private/internal "
                f"address ({resolved_addr}): {url}"
            )
            raise ValueError(msg)


@runtime_checkable
class HTTPClient(Protocol):
    """Minimal HTTP client for marketplace fetches."""

    async def get(self, url: str) -> HTTPResponse:
        """Fetch a URL. Returns HTTPResponse."""
        ...


class HTTPResponse:
    """Simple HTTP response wrapper."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class SkillMarketplaceImpl:
    """Community skill search and installation."""

    def __init__(
        self,
        http_client: HTTPClient,
        skills_dir: Path,
        registry: InMemorySkillRegistry,
    ) -> None:
        self._http = http_client
        self._skills_dir = skills_dir / "community"
        self._registry = registry

    async def search(self, query: str, max_results: int = 10) -> list[SkillMetadata]:
        """Search for skills. Currently returns empty — marketplace integration TBD.

        Production: queries a marketplace API or GitHub code search.
        """
        # Placeholder — marketplace search requires external service
        return []

    async def install(
        self,
        url: str,
        trust_tier: str = "t2",
    ) -> SkillDefinition:
        """Install a skill from a URL.

        Fetches content, parses, security scans, saves to community dir,
        and registers with the specified trust tier.

        Raises ValueError on fetch failure, parse failure, or security rejection.
        """
        # SSRF protection: block private/link-local/metadata URLs
        _block_ssrf(url)

        # Fetch
        try:
            resp = await self._http.get(url)
        except Exception as e:
            msg = f"Failed to fetch skill from {url}: {e}"
            raise ValueError(msg) from e

        if resp.status_code != 200:  # noqa: PLR2004
            msg = f"Skill fetch returned {resp.status_code} from {url}"
            raise ValueError(msg)

        content = resp.text

        # Security scan
        safe, findings = security_scan(content)
        if not safe:
            msg = f"Skill rejected by security scan: {', '.join(findings)}"
            raise ValueError(msg)

        # Parse
        skill = parse_skill_file(content, source=url)
        if skill is None:
            msg = f"Failed to parse skill from {url}"
            raise ValueError(msg)

        # Override trust tier
        skill = SkillDefinition(
            name=skill.name,
            description=skill.description,
            groups=skill.groups,
            parameters=skill.parameters,
            endpoint=skill.endpoint,
            auth_key_env=skill.auth_key_env,
            system_prompt=skill.system_prompt,
            source=url,
            trust_tier=trust_tier,
        )

        # Save to community directory
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._skills_dir / f"{skill.name}.md"
        filepath.write_text(content, encoding="utf-8")

        # Register
        self._registry.register(skill)

        logger.info(
            "Installed skill '%s' from %s (tier=%s, warnings=%d)",
            skill.name,
            url,
            trust_tier,
            len([f for f in findings if f.startswith("WARNING:")]),
        )

        return skill

    def uninstall(self, name: str) -> None:
        """Uninstall a community skill by name.

        Removes from registry and deletes the file.
        Raises ValueError if not found.
        """
        filepath = self._skills_dir / f"{name}.md"
        if not filepath.exists():
            msg = f"Community skill '{name}' not found"
            raise ValueError(msg)

        filepath.unlink()
        self._registry.delete(name)
        logger.info("Uninstalled skill: %s", name)
