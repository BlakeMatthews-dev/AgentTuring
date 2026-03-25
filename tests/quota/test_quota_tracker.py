"""Tests for InMemoryQuotaTracker: usage recording and percentage tracking."""

import pytest

from stronghold.quota.tracker import InMemoryQuotaTracker


class TestRecordUsage:
    """Recording usage increases total tokens."""

    @pytest.mark.asyncio
    async def test_record_increases_total(self) -> None:
        tracker = InMemoryQuotaTracker()
        result = await tracker.record_usage("provider_a", "monthly", 100, 50)
        assert result["total_tokens"] == 150
        assert result["provider"] == "provider_a"

    @pytest.mark.asyncio
    async def test_multiple_records_accumulate(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 100, 50)
        result = await tracker.record_usage("p", "monthly", 200, 100)
        assert result["total_tokens"] == 450

    @pytest.mark.asyncio
    async def test_request_count_increments(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 10, 5)
        await tracker.record_usage("p", "monthly", 20, 10)
        result = await tracker.record_usage("p", "monthly", 30, 15)
        assert result["request_count"] == 3

    @pytest.mark.asyncio
    async def test_input_and_output_tracked_separately(self) -> None:
        tracker = InMemoryQuotaTracker()
        result = await tracker.record_usage("p", "monthly", 100, 200)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 200
        assert result["total_tokens"] == 300

    @pytest.mark.asyncio
    async def test_zero_tokens(self) -> None:
        tracker = InMemoryQuotaTracker()
        result = await tracker.record_usage("p", "monthly", 0, 0)
        assert result["total_tokens"] == 0
        assert result["request_count"] == 1


class TestGetUsagePct:
    """get_usage_pct returns correct percentage."""

    @pytest.mark.asyncio
    async def test_basic_percentage(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 500, 500)
        pct = await tracker.get_usage_pct("p", "monthly", 10000)
        assert abs(pct - 0.1) < 0.001  # 1000/10000 = 10%

    @pytest.mark.asyncio
    async def test_zero_usage_zero_pct(self) -> None:
        tracker = InMemoryQuotaTracker()
        pct = await tracker.get_usage_pct("p", "monthly", 1000000)
        assert pct == 0.0

    @pytest.mark.asyncio
    async def test_full_usage(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 500, 500)
        pct = await tracker.get_usage_pct("p", "monthly", 1000)
        assert abs(pct - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_over_100_pct(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 1500, 500)
        pct = await tracker.get_usage_pct("p", "monthly", 1000)
        assert pct > 1.0

    @pytest.mark.asyncio
    async def test_zero_free_tokens_returns_zero(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "monthly", 100, 50)
        pct = await tracker.get_usage_pct("p", "monthly", 0)
        assert pct == 0.0

    @pytest.mark.asyncio
    async def test_negative_free_tokens_returns_zero(self) -> None:
        tracker = InMemoryQuotaTracker()
        pct = await tracker.get_usage_pct("p", "monthly", -1000)
        assert pct == 0.0


class TestMultipleProviders:
    """Multiple providers tracked independently."""

    @pytest.mark.asyncio
    async def test_independent_tracking(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("provider_a", "monthly", 1000, 0)
        await tracker.record_usage("provider_b", "monthly", 500, 0)

        pct_a = await tracker.get_usage_pct("provider_a", "monthly", 10000)
        pct_b = await tracker.get_usage_pct("provider_b", "monthly", 10000)

        assert abs(pct_a - 0.1) < 0.001
        assert abs(pct_b - 0.05) < 0.001

    @pytest.mark.asyncio
    async def test_many_providers(self) -> None:
        tracker = InMemoryQuotaTracker()
        for i in range(10):
            await tracker.record_usage(f"p{i}", "monthly", (i + 1) * 100, 0)

        for i in range(10):
            pct = await tracker.get_usage_pct(f"p{i}", "monthly", 10000)
            expected = (i + 1) * 100 / 10000
            assert abs(pct - expected) < 0.001

    @pytest.mark.asyncio
    async def test_different_billing_cycles(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p", "daily", 100, 0)
        await tracker.record_usage("p", "monthly", 200, 0)

        # These use different cycle keys, so they're tracked separately
        pct_daily = await tracker.get_usage_pct("p", "daily", 1000)
        pct_monthly = await tracker.get_usage_pct("p", "monthly", 1000)

        assert abs(pct_daily - 0.1) < 0.001
        assert abs(pct_monthly - 0.2) < 0.001


class TestGetAllUsage:
    """get_all_usage returns all records."""

    @pytest.mark.asyncio
    async def test_empty_returns_empty(self) -> None:
        tracker = InMemoryQuotaTracker()
        all_usage = await tracker.get_all_usage()
        assert all_usage == []

    @pytest.mark.asyncio
    async def test_single_provider(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p1", "monthly", 100, 50)
        all_usage = await tracker.get_all_usage()
        assert len(all_usage) == 1
        assert all_usage[0]["provider"] == "p1"
        assert all_usage[0]["total_tokens"] == 150

    @pytest.mark.asyncio
    async def test_multiple_providers(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p1", "monthly", 100, 0)
        await tracker.record_usage("p2", "monthly", 200, 0)
        all_usage = await tracker.get_all_usage()
        assert len(all_usage) == 2
        providers = {u["provider"] for u in all_usage}
        assert providers == {"p1", "p2"}


class TestEdgeCases:
    """Edge cases for quota tracker."""

    @pytest.mark.asyncio
    async def test_large_token_counts(self) -> None:
        tracker = InMemoryQuotaTracker()
        result = await tracker.record_usage("p", "monthly", 1_000_000_000, 500_000_000)
        assert result["total_tokens"] == 1_500_000_000

    @pytest.mark.asyncio
    async def test_unused_provider_zero_pct(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("p1", "monthly", 1000, 0)
        pct = await tracker.get_usage_pct("p2", "monthly", 10000)
        assert pct == 0.0

    @pytest.mark.asyncio
    async def test_concurrent_providers_no_interference(self) -> None:
        tracker = InMemoryQuotaTracker()
        for _ in range(100):
            await tracker.record_usage("fast_provider", "monthly", 1, 1)
        await tracker.record_usage("slow_provider", "monthly", 1000, 0)
        pct_fast = await tracker.get_usage_pct("fast_provider", "monthly", 1000)
        pct_slow = await tracker.get_usage_pct("slow_provider", "monthly", 1000)
        assert abs(pct_fast - 0.2) < 0.001  # 200/1000
        assert abs(pct_slow - 1.0) < 0.001  # 1000/1000
