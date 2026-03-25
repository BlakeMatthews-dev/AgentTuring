"""Tests for Sentinel audit log."""

import pytest

from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.types.security import AuditEntry


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_log_and_retrieve(self) -> None:
        log = InMemoryAuditLog()
        entry = AuditEntry(
            boundary="system_to_tool",
            user_id="blake",
            agent_id="warden-at-arms",
            tool_name="ha_control",
            verdict="allowed",
        )
        await log.log(entry)
        entries = await log.get_entries()
        assert len(entries) == 1
        assert entries[0].tool_name == "ha_control"

    @pytest.mark.asyncio
    async def test_filter_by_user(self) -> None:
        log = InMemoryAuditLog()
        await log.log(AuditEntry(user_id="blake", verdict="allowed"))
        await log.log(AuditEntry(user_id="other", verdict="allowed"))
        entries = await log.get_entries(user_id="blake")
        assert len(entries) == 1
