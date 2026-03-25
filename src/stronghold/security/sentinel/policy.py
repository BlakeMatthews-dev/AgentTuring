"""Sentinel policy enforcement: pre-call and post-call security pipeline.

Pre-call: validate + repair args, check permissions, audit log.
Post-call: Warden scan tool result, PII filter, token optimize, audit log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.security.sentinel.pii_filter import scan_and_redact
from stronghold.security.sentinel.token_optimizer import optimize_result
from stronghold.security.sentinel.validator import validate_and_repair
from stronghold.types.security import AuditEntry, SentinelVerdict, Violation, WardenVerdict

logger = logging.getLogger("stronghold.sentinel")

if TYPE_CHECKING:
    from stronghold.protocols.memory import AuditLog
    from stronghold.security.warden.detector import Warden
    from stronghold.types.auth import AuthContext, PermissionTable


def check_permission(
    auth_context: AuthContext,
    tool_name: str,
    permission_table: PermissionTable,
) -> bool:
    """Check if user's roles allow this tool."""
    return auth_context.can_use_tool(tool_name, permission_table)


class Sentinel:
    """Policy enforcement at every boundary crossing.

    Pre-call: validates args, checks permissions, logs audit.
    Post-call: scans result for threats + PII, optimizes tokens, logs audit.
    """

    def __init__(
        self,
        *,
        warden: Warden,
        permission_table: PermissionTable,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._warden = warden
        self._permission_table = permission_table
        self._audit_log = audit_log

    async def pre_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        auth: AuthContext,
        schema: dict[str, Any],
    ) -> SentinelVerdict:
        """Pre-call check: permissions + schema validation + repair.

        Returns SentinelVerdict. If not allowed, the tool MUST NOT be called.
        """
        violations: list[Violation] = []

        # 1. Permission check
        if not check_permission(auth, tool_name, self._permission_table):
            violations.append(
                Violation(
                    boundary="pre_call",
                    rule="permission_denied",
                    severity="error",
                    detail=f"User '{auth.user_id}' lacks permission for tool '{tool_name}'",
                )
            )
            verdict = SentinelVerdict(
                allowed=False,
                violations=tuple(violations),
            )
            await self._log_audit(
                boundary="pre_call",
                user_id=auth.user_id,
                org_id=auth.org_id,
                team_id=auth.team_id,
                tool_name=tool_name,
                verdict="denied",
                violations=tuple(violations),
            )
            return verdict

        # 2. Schema validation + repair
        schema_verdict = validate_and_repair(args, schema)
        if schema_verdict.violations:
            violations.extend(schema_verdict.violations)

        verdict = SentinelVerdict(
            allowed=True,
            repaired=schema_verdict.repaired,
            repaired_data=schema_verdict.repaired_data,
            violations=tuple(violations),
        )

        await self._log_audit(
            boundary="pre_call",
            user_id=auth.user_id,
            org_id=auth.org_id,
            team_id=auth.team_id,
            tool_name=tool_name,
            verdict="allowed" if verdict.allowed else "denied",
            violations=tuple(violations),
            detail=f"repaired={schema_verdict.repaired}" if schema_verdict.repaired else "",
            repaired_data=schema_verdict.repaired_data if schema_verdict.repaired else None,
        )

        return verdict

    async def post_call(
        self,
        tool_name: str,
        result: str,
        auth: AuthContext,
    ) -> str:
        """Post-call check: Warden scan + PII filter + token optimize.

        Returns the (possibly redacted/flagged + optimized) result string.

        Three outcomes for Warden flags:
        - blocked (L1 hard block): result replaced with block message
        - flagged (L2/L2.5/L3 soft flag): result KEPT but annotated with
          warning banner + admin notification + user escalation link
        - clean: result passes through unchanged
        """
        violations: list[Violation] = []
        processed = result

        # 1. Warden scan for tool result injection
        warden_verdict = await self._warden.scan(processed, "tool_result")
        if not warden_verdict.clean:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="warden_tool_result",
                    severity="warning" if not warden_verdict.blocked else "error",
                    detail=f"Warden flags: {', '.join(warden_verdict.flags)}",
                )
            )
            if warden_verdict.blocked:
                # Hard block: L1 regex matches (direct injection)
                processed = "[Tool result blocked by Warden — contained injection attempt]"
            else:
                # Soft flag: L2/L2.5/L3 detection — flag and warn, don't block
                from stronghold.security.warden.flag_response import (  # noqa: PLC0415
                    build_audit_payload,
                    build_flagged_response,
                )

                processed = build_flagged_response(
                    processed,
                    flags=list(warden_verdict.flags),
                    detection_layer=_detection_layer(warden_verdict),
                    flag_id=f"{auth.org_id}:{tool_name}:{id(result)}",
                    admin_email=f"security@{auth.org_id or 'stronghold'}.local",
                )
                # Structured audit for SIEM/alerting
                _audit_payload = build_audit_payload(
                    tool_name=tool_name,
                    flags=list(warden_verdict.flags),
                    detection_layer=_detection_layer(warden_verdict),
                    user_id=auth.user_id,
                    org_id=auth.org_id,
                    content_preview=result[:200],
                )
                logger.warning(
                    "Tool result flagged: tool=%s, user=%s, org=%s, flags=%s",
                    tool_name,
                    auth.user_id,
                    auth.org_id,
                    warden_verdict.flags,
                )

        # 2. PII filter — redact secrets and sensitive data
        processed, pii_matches = scan_and_redact(processed)
        if pii_matches:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="pii_detected",
                    severity="warning",
                    detail=f"Redacted {len(pii_matches)} PII pattern(s): "
                    + ", ".join(m.pii_type for m in pii_matches),
                )
            )

        # 3. Token optimization — compress bloated results
        processed = optimize_result(processed, tool_name)

        # 4. Audit log
        await self._log_audit(
            boundary="post_call",
            user_id=auth.user_id,
            org_id=auth.org_id,
            team_id=auth.team_id,
            tool_name=tool_name,
            verdict="clean" if not violations else "flagged",
            violations=tuple(violations),
        )

        return processed

    async def _log_audit(
        self,
        *,
        boundary: str,
        user_id: str,
        org_id: str = "",
        team_id: str = "",
        tool_name: str,
        verdict: str,
        violations: tuple[Violation, ...] = (),
        detail: str = "",
        repaired_data: dict[str, Any] | None = None,
    ) -> None:
        """Log an audit entry if audit_log is configured.

        Never raises — audit failures are logged but do not block the request.
        """
        if self._audit_log is None:
            return
        # Include repaired values in audit detail for forensics (#23)
        if repaired_data and not detail:
            detail = f"repaired_data_keys={list(repaired_data.keys())}"
        try:
            await self._audit_log.log(
                AuditEntry(
                    boundary=boundary,
                    user_id=user_id,
                    org_id=org_id,
                    team_id=team_id,
                    tool_name=tool_name,
                    verdict=verdict,
                    violations=violations,
                    detail=detail,
                )
            )
        except Exception:
            logger.exception("Audit log write failed (boundary=%s, tool=%s)", boundary, tool_name)


def _detection_layer(verdict: WardenVerdict) -> str:
    """Infer which Warden layer produced the flag."""
    for flag in verdict.flags:
        if flag.startswith("llm_classification"):
            return "Layer 3 (LLM)"
        if flag.startswith("prescriptive_"):
            return "Layer 2.5 (Semantic)"
        if flag.startswith("high_instruction") or flag.startswith("encoded_"):
            return "Layer 2 (Heuristic)"
    return "Layer 1 (Pattern)"
