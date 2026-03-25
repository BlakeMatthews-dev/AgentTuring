"""Tests for quota tracker."""

import pytest

from stronghold.quota.tracker import InMemoryQuotaTracker


class TestQuotaTracker:
    @pytest.mark.asyncio
    async def test_record_and_retrieve(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("mistral", "monthly", 100, 50)
        pct = await tracker.get_usage_pct("mistral", "monthly", 1000)
        assert pct == 0.15  # 150 / 1000

    @pytest.mark.asyncio
    async def test_accumulates(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("mistral", "monthly", 100, 50)
        await tracker.record_usage("mistral", "monthly", 200, 100)
        pct = await tracker.get_usage_pct("mistral", "monthly", 1000)
        assert pct == 0.45  # 450 / 1000

    @pytest.mark.asyncio
    async def test_zero_free_tokens_returns_zero(self) -> None:
        tracker = InMemoryQuotaTracker()
        pct = await tracker.get_usage_pct("mistral", "monthly", 0)
        assert pct == 0.0

    @pytest.mark.asyncio
    async def test_get_all_usage(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("mistral", "monthly", 100, 50)
        await tracker.record_usage("google", "daily", 200, 100)
        all_usage = await tracker.get_all_usage()
        assert len(all_usage) == 2
