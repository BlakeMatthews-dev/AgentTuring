"""Gate: input processing — sanitize, scan, strike, clarify.

The Gate is the first thing user input touches. Three execution modes:
- best_effort: sanitize + Warden scan. Block if malicious, pass through otherwise.
- persistent: + request sufficiency check. Returns clarifying questions if insufficient.
- supervised: always returns clarifying questions (human-in-the-loop).

Strike escalation (when Warden blocks):
- Strike 1: Warning + elevated scrutiny (L3 classifier enabled)
- Strike 2: 8-hour lockout (team_admin+ to unlock)
- Strike 3: Account disabled (org_admin+ to re-enable)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stronghold.agents.request_analyzer import (
    MissingDetail,
    analyze_request_sufficiency,
)
from stronghold.security.warden.sanitizer import sanitize
from stronghold.types.security import ClarifyingQuestion, GateResult

if TYPE_CHECKING:
    from stronghold.security.strikes import InMemoryStrikeTracker
    from stronghold.security.warden.detector import Warden
    from stronghold.types.auth import AuthContext

logger = logging.getLogger("stronghold.gate")


class Gate:
    """Processes user input before it reaches the Conduit.

    Takes Warden and StrikeTracker as constructor dependencies (DI).
    """

    def __init__(
        self,
        warden: Warden | None = None,
        strike_tracker: InMemoryStrikeTracker | None = None,
    ) -> None:
        if warden is None:
            from stronghold.security.warden.detector import (  # noqa: PLC0415
                Warden as WardenImpl,
            )

            warden = WardenImpl()
        self._warden = warden
        self._strike_tracker = strike_tracker

    async def process_input(
        self,
        content: str,
        *,
        execution_mode: str = "best_effort",
        task_type: str = "chat",
        conversation_context: list[dict[str, str]] | None = None,
        auth: AuthContext | None = None,
    ) -> GateResult:
        """Process user input through the security pipeline.

        Steps:
        1. Check if user is locked out or disabled (if auth + strike_tracker)
        2. Sanitize (remove zero-width chars, normalize whitespace)
        3. Warden scan (detect prompt injection, role hijacking, etc.)
        4. If blocked: record strike, escalate, return rich response
        5. If persistent mode: check request sufficiency
        6. If supervised mode: always return clarifying questions
        """
        user_id = auth.user_id if auth else ""
        org_id = auth.org_id if auth else ""

        # Step 1: Check lockout/disabled status
        if self._strike_tracker and user_id:
            record = await self._strike_tracker.get(user_id)
            if record and record.is_locked:
                locked_str = record.locked_until.isoformat() if record.locked_until else ""
                if record.disabled:
                    return GateResult(
                        blocked=True,
                        block_reason=(
                            "Your account has been disabled due to repeated security violations. "
                            "An organization administrator must re-enable your account."
                        ),
                        strike_number=record.strike_count,
                        scrutiny_level=record.scrutiny_level,
                        locked_until=locked_str,
                        account_disabled=True,
                    )
                return GateResult(
                    blocked=True,
                    block_reason=(
                        "Your account is temporarily locked due to security violations. "
                        "A team administrator must unlock your account, or the lockout "
                        f"expires at {locked_str}."
                    ),
                    strike_number=record.strike_count,
                    scrutiny_level=record.scrutiny_level,
                    locked_until=locked_str,
                )

        # Step 2: Sanitize
        sanitized = sanitize(content)

        # Step 3: Warden scan
        verdict = await self._warden.scan(sanitized, "user_input")

        # Step 4: Block if ANY Warden flags detected + record strike
        if not verdict.clean:
            strike_number = 0
            scrutiny_level = "normal"
            locked_until = ""
            disabled = False

            # Record the strike (if tracker + auth available)
            if self._strike_tracker and user_id:
                record = await self._strike_tracker.record_violation(
                    user_id=user_id,
                    org_id=org_id,
                    flags=verdict.flags,
                    boundary="user_input",
                    detail=f"Gate block: {', '.join(verdict.flags)}",
                )
                strike_number = record.strike_count
                scrutiny_level = record.scrutiny_level
                locked_until = record.locked_until.isoformat() if record.locked_until else ""
                disabled = record.disabled

            logger.warning(
                "GATE BLOCK: user=%s flags=%s strike=%d level=%s",
                user_id or "anonymous",
                verdict.flags,
                strike_number,
                scrutiny_level,
            )

            return GateResult(
                sanitized_text=sanitized,
                warden_verdict=verdict,
                blocked=True,
                block_reason=f"Blocked by Warden: {', '.join(verdict.flags)}",
                strike_number=strike_number,
                scrutiny_level=scrutiny_level,
                locked_until=locked_until,
                account_disabled=disabled,
            )

        # Step 5: Persistent mode — check sufficiency
        if execution_mode == "persistent":
            sufficiency = analyze_request_sufficiency(
                sanitized,
                task_type,
                conversation_context=conversation_context,
            )
            if not sufficiency.sufficient:
                questions = _missing_to_questions(sufficiency.missing)
                return GateResult(
                    sanitized_text=sanitized,
                    warden_verdict=verdict,
                    clarifying_questions=tuple(questions),
                )

        # Step 6: Supervised mode — always ask for confirmation
        if execution_mode == "supervised":
            sufficiency = analyze_request_sufficiency(
                sanitized,
                task_type,
                conversation_context=conversation_context,
            )
            questions = _missing_to_questions(sufficiency.missing)
            if not questions:
                questions = [
                    ClarifyingQuestion(
                        question="I understood your request. Should I proceed?",
                        options=("Yes, go ahead", "No, let me clarify"),
                        allow_freetext=True,
                    )
                ]
            return GateResult(
                sanitized_text=sanitized,
                warden_verdict=verdict,
                clarifying_questions=tuple(questions),
            )

        # Best effort: pass through
        return GateResult(
            sanitized_text=sanitized,
            warden_verdict=verdict,
        )


def _missing_to_questions(missing: list[MissingDetail]) -> list[ClarifyingQuestion]:
    """Convert MissingDetail list to ClarifyingQuestion list."""
    return [
        ClarifyingQuestion(
            question=m.question,
            allow_freetext=True,
        )
        for m in missing
    ]
