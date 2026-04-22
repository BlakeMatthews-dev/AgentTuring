"""Tests for cache_breakpoints_enabled config field.

Spec: specs/phase3-plan-caching.yaml (spec 1012)
"""

from __future__ import annotations

from stronghold.types.config import StrongholdConfig


class TestCacheBreakpointsConfig:
    def test_default_off(self) -> None:
        """Invariant: default_off."""
        config = StrongholdConfig()
        assert config.cache_breakpoints_enabled is False

    def test_can_enable(self) -> None:
        config = StrongholdConfig(cache_breakpoints_enabled=True)
        assert config.cache_breakpoints_enabled is True
