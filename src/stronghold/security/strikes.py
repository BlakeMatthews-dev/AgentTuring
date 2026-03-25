"""Strike tracker: per-user violation escalation with lockout and disable.

Escalation ladder:
  Strike 1 — Warning + elevated scrutiny (L3 classifier enabled for user)
  Strike 2 — 8-hour lockout (requires team_admin+ to unlock)
  Strike 3 — Account disabled (requires org_admin+ to re-enable)

Admin actions:
  - Any admin can remove strikes (decrement or clear)
  - team_admin+ can unlock a locked account
  - org_admin+ can re-enable a disabled account
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("stronghold.strikes")

# Lockout duration for strike 2
LOCKOUT_DURATION = timedelta(hours=8)

# Scrutiny levels
NORMAL = "normal"
ELEVATED = "elevated"  # Strike 1: L3 enabled, stricter checks
LOCKED = "locked"  # Strike 2: 8-hour timeout
DISABLED = "disabled"  # Strike 3: account disabled


@dataclass
class ViolationRecord:
    """Individual violation event."""

    timestamp: datetime
    flags: tuple[str, ...]
    boundary: str  # "user_input" or "tool_result"
    detail: str = ""


@dataclass
class StrikeRecord:
    """Per-user strike state."""

    user_id: str
    org_id: str
    strike_count: int = 0
    scrutiny_level: str = NORMAL
    locked_until: datetime | None = None
    disabled: bool = False
    violations: list[ViolationRecord] = field(default_factory=list)
    last_violation_at: datetime | None = None
    # Appeal text submitted by user (most recent)
    last_appeal: str = ""
    last_appeal_at: datetime | None = None

    @property
    def is_locked(self) -> bool:
        """Check if the user is currently in lockout period."""
        if self.disabled:
            return True
        if self.locked_until is not None:
            return datetime.now(UTC) < self.locked_until
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "user_id": self.user_id,
            "org_id": self.org_id,
            "strike_count": self.strike_count,
            "scrutiny_level": self.scrutiny_level,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "disabled": self.disabled,
            "is_locked": self.is_locked,
            "violation_count": len(self.violations),
            "last_violation_at": (
                self.last_violation_at.isoformat() if self.last_violation_at else None
            ),
            "last_appeal": self.last_appeal,
        }


class InMemoryStrikeTracker:
    """In-memory strike tracker. Production should use PgStrikeTracker."""

    def __init__(self) -> None:
        self._records: dict[str, StrikeRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> StrikeRecord | None:
        """Get strike record for a user."""
        return self._records.get(user_id)

    async def record_violation(
        self,
        *,
        user_id: str,
        org_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        """Record a violation and escalate strike level.

        Returns the updated StrikeRecord with new strike state.
        Uses async lock to prevent race conditions on concurrent requests.
        """
        async with self._lock:
            now = datetime.now(UTC)

            record = self._records.get(user_id)
            if record is None:
                record = StrikeRecord(user_id=user_id, org_id=org_id)
                self._records[user_id] = record

            # Record the violation
            violation = ViolationRecord(
                timestamp=now,
                flags=flags,
                boundary=boundary,
                detail=detail,
            )
            record.violations.append(violation)
            record.last_violation_at = now

            # Escalate
            record.strike_count += 1

            if record.strike_count >= 3:
                record.scrutiny_level = DISABLED
                record.disabled = True
                logger.warning(
                    "ACCOUNT DISABLED: user=%s org=%s strikes=%d",
                    user_id,
                    org_id,
                    record.strike_count,
                )
            elif record.strike_count == 2:
                record.scrutiny_level = LOCKED
                record.locked_until = now + LOCKOUT_DURATION
                logger.warning(
                    "ACCOUNT LOCKED: user=%s org=%s until=%s",
                    user_id,
                    org_id,
                    record.locked_until.isoformat(),
                )
            elif record.strike_count == 1:
                record.scrutiny_level = ELEVATED
                logger.warning(
                    "STRIKE 1: user=%s org=%s — elevated scrutiny enabled",
                    user_id,
                    org_id,
                )

            return record

    async def submit_appeal(
        self,
        user_id: str,
        appeal_text: str,
    ) -> bool:
        """Submit an appeal for a strike. Returns True if recorded."""
        record = self._records.get(user_id)
        if record is None or record.strike_count == 0:
            return False
        record.last_appeal = appeal_text
        record.last_appeal_at = datetime.now(UTC)
        logger.info("Appeal submitted: user=%s text=%s", user_id, appeal_text[:100])
        return True

    async def remove_strikes(
        self,
        user_id: str,
        count: int | None = None,
    ) -> StrikeRecord | None:
        """Remove strikes from a user. count=None clears all.

        Called by admins. Recalculates scrutiny level.
        """
        record = self._records.get(user_id)
        if record is None:
            return None

        if count is None:
            record.strike_count = 0
        else:
            record.strike_count = max(0, record.strike_count - count)

        # Recalculate scrutiny level based on new count
        self._recalculate_level(record)

        logger.info(
            "Strikes removed: user=%s new_count=%d level=%s",
            user_id,
            record.strike_count,
            record.scrutiny_level,
        )
        return record

    async def unlock(self, user_id: str) -> StrikeRecord | None:
        """Unlock a locked account (team_admin+ action).

        Clears the lockout timer but does NOT remove strikes.
        """
        record = self._records.get(user_id)
        if record is None:
            return None

        record.locked_until = None
        # Recalculate: if still at 2+ strikes, stay elevated but unlocked
        if not record.disabled:
            record.scrutiny_level = ELEVATED if record.strike_count >= 1 else NORMAL

        logger.info("Account unlocked: user=%s", user_id)
        return record

    async def enable(self, user_id: str) -> StrikeRecord | None:
        """Re-enable a disabled account (org_admin+ action).

        Clears disabled flag and lockout but does NOT remove strikes.
        """
        record = self._records.get(user_id)
        if record is None:
            return None

        record.disabled = False
        record.locked_until = None
        record.scrutiny_level = ELEVATED if record.strike_count >= 1 else NORMAL

        logger.info("Account re-enabled: user=%s", user_id)
        return record

    async def get_all_for_org(self, org_id: str) -> list[StrikeRecord]:
        """Get all strike records for an org (admin view)."""
        return [r for r in self._records.values() if r.org_id == org_id]

    @staticmethod
    def _recalculate_level(record: StrikeRecord) -> None:
        """Recalculate scrutiny level from strike count."""
        if record.strike_count >= 3:
            record.scrutiny_level = DISABLED
            record.disabled = True
        elif record.strike_count == 2:
            record.scrutiny_level = LOCKED
            # Don't re-lock if admin already unlocked
        elif record.strike_count >= 1:
            record.scrutiny_level = ELEVATED
            record.disabled = False
            record.locked_until = None
        else:
            record.scrutiny_level = NORMAL
            record.disabled = False
            record.locked_until = None
