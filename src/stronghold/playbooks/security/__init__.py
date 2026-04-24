"""Security playbooks — composed vulnerability scans over a workspace."""

from __future__ import annotations

from stronghold.playbooks.security.scan_for_vulnerabilities import (
    ScanForVulnerabilitiesPlaybook,
    scan_for_vulnerabilities,
)

__all__ = ["ScanForVulnerabilitiesPlaybook", "scan_for_vulnerabilities"]
