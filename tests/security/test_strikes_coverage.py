"""Integration tests for the strike tracker escalation system.

Covers the full warn -> throttle -> block -> ban ladder, plus admin actions
(remove_strikes, unlock, enable), appeal submission, lockout expiry,
to_dict serialization, and _recalculate_level edge cases.

Uses real InMemoryStrikeTracker -- no mocks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stronghold.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    LOCKOUT_DURATION,
    NORMAL,
    InMemoryStrikeTracker,
    StrikeRecord,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_tracker() -> InMemoryStrikeTracker:
    return InMemoryStrikeTracker()


async def _record_n_violations(
    tracker: InMemoryStrikeTracker,
    n: int,
    *,
    user_id: str = "u1",
    org_id: str = "acme",
) -> StrikeRecord:
    """Record *n* violations and return the final StrikeRecord."""
    record = None
    for _ in range(n):
        record = await tracker.record_violation(
            user_id=user_id,
            org_id=org_id,
            flags=("test_flag",),
            boundary="user_input",
            detail="test violation",
        )
    assert record is not None
    return record


# ═══════════════════════════════════════════════════════════════════════
# Strike Escalation Ladder
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestStrikeEscalation:
    """Verify the warn -> lock -> disable escalation ladder."""

    async def test_strike_1_elevated_scrutiny(self) -> None:
        """First violation sets scrutiny to ELEVATED."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 1)

        assert record.strike_count == 1
        assert record.scrutiny_level == ELEVATED
        assert not record.disabled
        assert record.locked_until is None

    async def test_strike_2_locked_with_duration(self) -> None:
        """Second violation locks the account for LOCKOUT_DURATION."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 2)

        assert record.strike_count == 2
        assert record.scrutiny_level == LOCKED
        assert record.locked_until is not None
        assert not record.disabled
        # Lockout should be ~8 hours from now
        expected_min = datetime.now(UTC) + LOCKOUT_DURATION - timedelta(seconds=5)
        assert record.locked_until >= expected_min

    async def test_strike_3_account_disabled(self) -> None:
        """Third violation disables the account entirely."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 3)

        assert record.strike_count == 3
        assert record.scrutiny_level == DISABLED
        assert record.disabled is True

    async def test_strike_4_stays_disabled(self) -> None:
        """Fourth+ violations keep account disabled, increment count."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 4)

        assert record.strike_count == 4
        assert record.scrutiny_level == DISABLED
        assert record.disabled is True

    async def test_violations_accumulate(self) -> None:
        """Each violation appends to the violations list."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 3)

        assert len(record.violations) == 3
        assert record.last_violation_at is not None

    async def test_first_violation_creates_record(self) -> None:
        """record_violation for unknown user creates a new StrikeRecord."""
        tracker = _make_tracker()
        assert await tracker.get("new_user") is None

        await tracker.record_violation(
            user_id="new_user",
            org_id="acme",
            flags=("inject",),
            boundary="tool_result",
            detail="attempt",
        )
        record = await tracker.get("new_user")
        assert record is not None
        assert record.org_id == "acme"
        assert record.violations[0].boundary == "tool_result"
        assert record.violations[0].flags == ("inject",)
        assert record.violations[0].detail == "attempt"


# ═══════════════════════════════════════════════════════════════════════
# is_locked Property (lines 60-67)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestIsLockedProperty:
    """Cover StrikeRecord.is_locked -- disabled, active lock, expired lock."""

    async def test_disabled_user_is_locked(self) -> None:
        """Disabled accounts always report is_locked=True."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 3)

        assert record.disabled is True
        assert record.is_locked is True

    async def test_active_lockout_is_locked(self) -> None:
        """User with future locked_until is locked."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 2)

        assert record.locked_until is not None
        assert record.is_locked is True

    async def test_expired_lockout_is_not_locked(self) -> None:
        """User whose lockout has expired is no longer locked."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 2)

        # Manually expire the lockout (simulate 9 hours passing)
        record.locked_until = datetime.now(UTC) - timedelta(hours=1)
        assert record.is_locked is False

    async def test_no_lockout_not_locked(self) -> None:
        """User with no lock and not disabled is not locked."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 1)

        assert record.locked_until is None
        assert record.disabled is False
        assert record.is_locked is False


# ═══════════════════════════════════════════════════════════════════════
# to_dict Serialization (line 70)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestToDict:
    """Cover StrikeRecord.to_dict serialization."""

    async def test_to_dict_fresh_record(self) -> None:
        """to_dict on strike-1 record includes all expected keys."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 1)
        d = record.to_dict()

        assert d["user_id"] == "u1"
        assert d["org_id"] == "acme"
        assert d["strike_count"] == 1
        assert d["scrutiny_level"] == ELEVATED
        assert d["locked_until"] is None
        assert d["disabled"] is False
        assert d["is_locked"] is False
        assert d["violation_count"] == 1
        assert d["last_violation_at"] is not None
        assert d["last_appeal"] == ""

    async def test_to_dict_locked_record(self) -> None:
        """to_dict correctly serializes locked_until as ISO string."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 2)
        d = record.to_dict()

        assert d["locked_until"] is not None
        # Should be a valid ISO timestamp string
        datetime.fromisoformat(d["locked_until"])
        assert d["is_locked"] is True
        assert d["scrutiny_level"] == LOCKED

    async def test_to_dict_disabled_record(self) -> None:
        """to_dict on disabled record shows disabled=True and is_locked=True."""
        tracker = _make_tracker()
        record = await _record_n_violations(tracker, 3)
        d = record.to_dict()

        assert d["disabled"] is True
        assert d["is_locked"] is True
        assert d["scrutiny_level"] == DISABLED
        assert d["violation_count"] == 3

    async def test_to_dict_no_violations(self) -> None:
        """to_dict on a clean record (no violations) serializes correctly."""
        record = StrikeRecord(user_id="u_clean", org_id="acme")
        d = record.to_dict()

        assert d["strike_count"] == 0
        assert d["violation_count"] == 0
        assert d["last_violation_at"] is None
        assert d["locked_until"] is None
        assert d["disabled"] is False
        assert d["is_locked"] is False
        assert d["last_appeal"] == ""


# ═══════════════════════════════════════════════════════════════════════
# Appeal Submission (lines 163-169)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSubmitAppeal:
    """Cover submit_appeal -- success, no record, no strikes."""

    async def test_appeal_success(self) -> None:
        """Appeal on a user with strikes returns True and stores text."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 1)

        result = await tracker.submit_appeal("u1", "I was testing, sorry")
        assert result is True

        record = await tracker.get("u1")
        assert record is not None
        assert record.last_appeal == "I was testing, sorry"
        assert record.last_appeal_at is not None

    async def test_appeal_no_record_returns_false(self) -> None:
        """Appeal for unknown user returns False."""
        tracker = _make_tracker()
        result = await tracker.submit_appeal("nonexistent", "please")
        assert result is False

    async def test_appeal_zero_strikes_returns_false(self) -> None:
        """Appeal for user with record but 0 strikes returns False."""
        tracker = _make_tracker()
        # Create a record then clear strikes
        await _record_n_violations(tracker, 1)
        await tracker.remove_strikes("u1", count=None)

        record = await tracker.get("u1")
        assert record is not None
        assert record.strike_count == 0

        result = await tracker.submit_appeal("u1", "please reconsider")
        assert result is False

    async def test_appeal_overwrites_previous(self) -> None:
        """Submitting a new appeal overwrites the previous one."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 2)

        await tracker.submit_appeal("u1", "first appeal")
        await tracker.submit_appeal("u1", "second appeal")

        record = await tracker.get("u1")
        assert record is not None
        assert record.last_appeal == "second appeal"


# ═══════════════════════════════════════════════════════════════════════
# Remove Strikes (lines 180-198)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRemoveStrikes:
    """Cover remove_strikes -- clear all, partial removal, recalculation."""

    async def test_clear_all_strikes(self) -> None:
        """count=None clears all strikes and returns to NORMAL."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.remove_strikes("u1", count=None)
        assert record is not None
        assert record.strike_count == 0
        assert record.scrutiny_level == NORMAL
        assert record.disabled is False
        assert record.locked_until is None

    async def test_partial_removal_from_3_to_1(self) -> None:
        """Removing 2 strikes from 3 -> 1 -> ELEVATED, not disabled."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.remove_strikes("u1", count=2)
        assert record is not None
        assert record.strike_count == 1
        assert record.scrutiny_level == ELEVATED
        assert record.disabled is False
        assert record.locked_until is None

    async def test_partial_removal_from_3_to_2(self) -> None:
        """Removing 1 strike from 3 -> 2 -> LOCKED."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.remove_strikes("u1", count=1)
        assert record is not None
        assert record.strike_count == 2
        assert record.scrutiny_level == LOCKED

    async def test_removal_clamped_at_zero(self) -> None:
        """Removing more strikes than exist clamps to 0."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 1)

        record = await tracker.remove_strikes("u1", count=10)
        assert record is not None
        assert record.strike_count == 0
        assert record.scrutiny_level == NORMAL

    async def test_remove_from_unknown_user(self) -> None:
        """Removing strikes from nonexistent user returns None."""
        tracker = _make_tracker()
        result = await tracker.remove_strikes("ghost")
        assert result is None

    async def test_remove_strikes_count_zero(self) -> None:
        """Removing 0 strikes keeps count unchanged."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 2)

        record = await tracker.remove_strikes("u1", count=0)
        assert record is not None
        assert record.strike_count == 2


# ═══════════════════════════════════════════════════════════════════════
# Unlock (lines 205-215)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestUnlock:
    """Cover unlock -- clears lockout, keeps strikes, handles disabled."""

    async def test_unlock_clears_lockout(self) -> None:
        """Unlock removes locked_until but keeps strike count."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 2)

        record = await tracker.unlock("u1")
        assert record is not None
        assert record.locked_until is None
        assert record.strike_count == 2
        assert record.scrutiny_level == ELEVATED
        assert record.is_locked is False

    async def test_unlock_disabled_stays_disabled(self) -> None:
        """Unlocking a disabled account does not clear disabled flag."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.unlock("u1")
        assert record is not None
        # disabled=True means unlock doesn't downgrade scrutiny
        assert record.disabled is True
        # is_locked should still be True because disabled overrides
        assert record.is_locked is True

    async def test_unlock_unknown_user(self) -> None:
        """Unlocking nonexistent user returns None."""
        tracker = _make_tracker()
        result = await tracker.unlock("ghost")
        assert result is None

    async def test_unlock_no_strikes_sets_normal(self) -> None:
        """Unlocking a user with 0 strikes sets NORMAL scrutiny."""
        tracker = _make_tracker()
        # Create record, then clear strikes, then lock manually
        await _record_n_violations(tracker, 2)
        await tracker.remove_strikes("u1", count=None)

        record = await tracker.get("u1")
        assert record is not None
        record.locked_until = datetime.now(UTC) + timedelta(hours=1)

        result = await tracker.unlock("u1")
        assert result is not None
        assert result.scrutiny_level == NORMAL
        assert result.locked_until is None


# ═══════════════════════════════════════════════════════════════════════
# Enable (lines 222-231)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestEnable:
    """Cover enable -- re-enables disabled account, clears lock, keeps strikes."""

    async def test_enable_clears_disabled(self) -> None:
        """Enable sets disabled=False and clears lockout."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.enable("u1")
        assert record is not None
        assert record.disabled is False
        assert record.locked_until is None
        # Still has strikes, so should be ELEVATED
        assert record.scrutiny_level == ELEVATED
        assert record.strike_count == 3

    async def test_enable_unknown_user(self) -> None:
        """Enabling nonexistent user returns None."""
        tracker = _make_tracker()
        result = await tracker.enable("ghost")
        assert result is None

    async def test_enable_then_is_not_locked(self) -> None:
        """After enable, is_locked should return False."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)

        record = await tracker.enable("u1")
        assert record is not None
        assert record.is_locked is False

    async def test_enable_zero_strikes_sets_normal(self) -> None:
        """Enabling a user with 0 strikes sets NORMAL scrutiny."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3)
        await tracker.remove_strikes("u1", count=None)

        # Manually set disabled back for this scenario
        rec = await tracker.get("u1")
        assert rec is not None
        rec.disabled = True

        record = await tracker.enable("u1")
        assert record is not None
        assert record.scrutiny_level == NORMAL
        assert record.disabled is False


# ═══════════════════════════════════════════════════════════════════════
# _recalculate_level (lines 240-253)
# ═══════════════════════════════════════════════════════════════════════


class TestRecalculateLevel:
    """Cover _recalculate_level static method with all branches."""

    def test_recalc_3_plus_disables(self) -> None:
        """3+ strikes -> DISABLED + disabled=True."""
        rec = StrikeRecord(user_id="u", org_id="o", strike_count=5)
        InMemoryStrikeTracker._recalculate_level(rec)

        assert rec.scrutiny_level == DISABLED
        assert rec.disabled is True

    def test_recalc_2_locks(self) -> None:
        """2 strikes -> LOCKED, does NOT re-lock (locked_until unchanged)."""
        rec = StrikeRecord(user_id="u", org_id="o", strike_count=2)
        InMemoryStrikeTracker._recalculate_level(rec)

        assert rec.scrutiny_level == LOCKED
        # locked_until should NOT be set by recalculate (admin may have unlocked)
        assert rec.locked_until is None

    def test_recalc_1_elevated(self) -> None:
        """1 strike -> ELEVATED, clears disabled and locked_until."""
        rec = StrikeRecord(
            user_id="u",
            org_id="o",
            strike_count=1,
            disabled=True,
            locked_until=datetime.now(UTC) + timedelta(hours=1),
        )
        InMemoryStrikeTracker._recalculate_level(rec)

        assert rec.scrutiny_level == ELEVATED
        assert rec.disabled is False
        assert rec.locked_until is None

    def test_recalc_0_normal(self) -> None:
        """0 strikes -> NORMAL, clears disabled and locked_until."""
        rec = StrikeRecord(
            user_id="u",
            org_id="o",
            strike_count=0,
            disabled=True,
            locked_until=datetime.now(UTC) + timedelta(hours=1),
        )
        InMemoryStrikeTracker._recalculate_level(rec)

        assert rec.scrutiny_level == NORMAL
        assert rec.disabled is False
        assert rec.locked_until is None

    def test_recalc_exactly_3_disables(self) -> None:
        """Exactly 3 -> DISABLED (boundary check)."""
        rec = StrikeRecord(user_id="u", org_id="o", strike_count=3)
        InMemoryStrikeTracker._recalculate_level(rec)

        assert rec.scrutiny_level == DISABLED
        assert rec.disabled is True


# ═══════════════════════════════════════════════════════════════════════
# Full Lifecycle: Escalate -> Admin Intervention -> Recovery
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestFullLifecycle:
    """End-to-end escalation and admin recovery scenarios."""

    async def test_full_escalation_then_enable_then_appeal(self) -> None:
        """User escalates to disabled, admin enables, user appeals."""
        tracker = _make_tracker()

        # Strike 1: warning
        r = await tracker.record_violation(
            user_id="alice",
            org_id="acme",
            flags=("prompt_injection",),
            boundary="user_input",
            detail="tried to leak system prompt",
        )
        assert r.scrutiny_level == ELEVATED

        # Strike 2: locked
        r = await tracker.record_violation(
            user_id="alice",
            org_id="acme",
            flags=("pii_leak",),
            boundary="tool_result",
            detail="exposed API key",
        )
        assert r.scrutiny_level == LOCKED
        assert r.is_locked is True

        # Strike 3: disabled
        r = await tracker.record_violation(
            user_id="alice",
            org_id="acme",
            flags=("data_exfil",),
            boundary="user_input",
            detail="bulk export attempt",
        )
        assert r.scrutiny_level == DISABLED
        assert r.disabled is True
        assert r.is_locked is True

        # Admin enables (org_admin action)
        r2 = await tracker.enable("alice")
        assert r2 is not None
        assert r2.disabled is False
        assert r2.scrutiny_level == ELEVATED
        assert r2.is_locked is False

        # User submits appeal
        ok = await tracker.submit_appeal("alice", "It was a research test, I apologize")
        assert ok is True

        rec = await tracker.get("alice")
        assert rec is not None
        assert rec.last_appeal == "It was a research test, I apologize"

    async def test_lock_then_unlock_then_remove(self) -> None:
        """User locked at strike 2, admin unlocks, then removes 1 strike."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 2, user_id="bob", org_id="acme")

        # Admin unlocks
        r = await tracker.unlock("bob")
        assert r is not None
        assert r.is_locked is False
        assert r.strike_count == 2
        assert r.scrutiny_level == ELEVATED

        # Admin removes 1 strike
        r2 = await tracker.remove_strikes("bob", count=1)
        assert r2 is not None
        assert r2.strike_count == 1
        assert r2.scrutiny_level == ELEVATED

        # Admin removes remaining strike
        r3 = await tracker.remove_strikes("bob", count=1)
        assert r3 is not None
        assert r3.strike_count == 0
        assert r3.scrutiny_level == NORMAL

    async def test_disable_then_remove_all_then_enable(self) -> None:
        """Disabled user: admin clears all strikes then enables."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 3, user_id="carol", org_id="acme")

        # Clear all strikes first
        r = await tracker.remove_strikes("carol", count=None)
        assert r is not None
        assert r.strike_count == 0
        assert r.scrutiny_level == NORMAL
        assert r.disabled is False

    async def test_get_all_for_org_returns_multiple_users(self) -> None:
        """get_all_for_org returns all users in that org."""
        tracker = _make_tracker()
        await _record_n_violations(tracker, 1, user_id="u1", org_id="acme")
        await _record_n_violations(tracker, 2, user_id="u2", org_id="acme")
        await _record_n_violations(tracker, 1, user_id="u3", org_id="other")

        acme_records = await tracker.get_all_for_org("acme")
        assert len(acme_records) == 2
        user_ids = {r.user_id for r in acme_records}
        assert user_ids == {"u1", "u2"}

    async def test_get_all_for_org_empty(self) -> None:
        """get_all_for_org returns empty list for unknown org."""
        tracker = _make_tracker()
        result = await tracker.get_all_for_org("nonexistent")
        assert result == []


# ═══════════════════════════════════════════════════════════════════════
# Violation Record Details
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestViolationRecordDetails:
    """Verify violation records capture boundary, flags, and detail."""

    async def test_violation_fields_captured(self) -> None:
        """Each violation records timestamp, flags, boundary, detail."""
        tracker = _make_tracker()
        await tracker.record_violation(
            user_id="u1",
            org_id="acme",
            flags=("injection", "exfil"),
            boundary="tool_result",
            detail="attempted data extraction via tool output",
        )

        record = await tracker.get("u1")
        assert record is not None
        assert len(record.violations) == 1

        v = record.violations[0]
        assert v.flags == ("injection", "exfil")
        assert v.boundary == "tool_result"
        assert v.detail == "attempted data extraction via tool output"
        # Exact datetime type (not a date or a string). Also require
        # a timezone — naive datetimes are a bug in the audit record.
        assert type(v.timestamp) is datetime
        assert v.timestamp.tzinfo is not None

    async def test_multiple_violations_ordered(self) -> None:
        """Violations are appended in order."""
        tracker = _make_tracker()
        await tracker.record_violation(
            user_id="u1",
            org_id="acme",
            flags=("first",),
            boundary="user_input",
        )
        await tracker.record_violation(
            user_id="u1",
            org_id="acme",
            flags=("second",),
            boundary="tool_result",
        )

        record = await tracker.get("u1")
        assert record is not None
        assert record.violations[0].flags == ("first",)
        assert record.violations[1].flags == ("second",)
