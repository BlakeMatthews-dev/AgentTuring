"""Flagged content response builder.

When Warden flags tool results (L2.5 semantic or L3 LLM), this module
builds the user-facing warning with:
1. The flagged content (still visible, not blocked)
2. A clear warning that it was flagged
3. Admin notification (via audit log)
4. User escalation path (email manager/admin if false positive)

Enterprise pattern: flag → warn → notify → escalate.
Never silently block. Never silently pass. Always transparent.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("stronghold.warden.flag")

_FLAG_BANNER = (
    "\n\n"
    "---\n"
    "⚠ SECURITY NOTICE: This tool result has been flagged by Stronghold Warden.\n"
    "Reason: {reason}\n"
    "Detection: {detection_layer}\n"
    "\n"
    "This content has been logged and an administrator has been notified.\n"
    "The result is shown above for your review — verify before acting on it.\n"
    "\n"
    "If you believe this is an error, escalate: {escalation_url}\n"
    "---"
)

# Default escalation URL template — org-specific override via config
_DEFAULT_ESCALATION_URL = (
    "mailto:{admin_email}?subject=Warden%20False%20Positive%20-%20{flag_id}"
    "&body=I%20believe%20the%20following%20Warden%20flag%20is%20a%20false%20positive"
    "%3A%0A%0AFlag%20ID%3A%20{flag_id}%0AReason%3A%20{reason}"
)


def build_flagged_response(
    original_content: str,
    *,
    flags: list[str],
    detection_layer: str,
    flag_id: str = "",
    admin_email: str = "security@stronghold.local",
    escalation_url: str = "",
) -> str:
    """Wrap flagged tool result with warning banner.

    The original content is preserved — the banner is APPENDED.
    This ensures the agent sees the data but also sees the warning.
    """
    reason = "; ".join(flags) if flags else "suspicious content detected"

    if not escalation_url:
        escalation_url = _DEFAULT_ESCALATION_URL.format(
            admin_email=admin_email,
            flag_id=flag_id or "unknown",
            reason=reason.replace(" ", "%20"),
        )

    banner = _FLAG_BANNER.format(
        reason=reason,
        detection_layer=detection_layer,
        escalation_url=escalation_url,
    )

    return original_content + banner


def build_audit_payload(
    *,
    tool_name: str,
    flags: list[str],
    detection_layer: str,
    user_id: str,
    org_id: str,
    content_preview: str = "",
    llm_classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build structured audit payload for flagged content.

    This goes into the audit log and can be forwarded to
    SIEM/alerting systems.
    """
    return {
        "event": "tool_result_flagged",
        "severity": "warning",
        "tool_name": tool_name,
        "flags": flags,
        "detection_layer": detection_layer,
        "user_id": user_id,
        "org_id": org_id,
        "content_preview": content_preview[:200],
        "llm_classification": llm_classification,
        "action": "flagged_and_warned",
        "requires_review": True,
    }
