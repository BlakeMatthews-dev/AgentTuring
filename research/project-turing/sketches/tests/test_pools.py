"""Tests for runtime/pools.py — PoolConfig + load_pools."""

from __future__ import annotations

from pathlib import Path

import pytest

from turing.runtime.pools import PoolConfig, load_pools


def test_pool_config_round_trip() -> None:
    pool = PoolConfig(
        pool_name="gemini-flash",
        model="gemini/gemini-2.0-flash-exp",
        window_kind="rpm",
        window_duration_seconds=60,
        tokens_allowed=1_000_000,
        quality_weight=0.7,
    )
    assert pool.pool_name == "gemini-flash"
    assert pool.model == "gemini/gemini-2.0-flash-exp"


def test_pool_rejects_invalid_window_kind() -> None:
    with pytest.raises(ValueError, match="window_kind"):
        PoolConfig(
            pool_name="x",
            model="x",
            window_kind="hourly_ish",
            window_duration_seconds=60,
            tokens_allowed=1,
        )


def test_pool_rejects_zero_tokens_allowed() -> None:
    with pytest.raises(ValueError, match="tokens_allowed"):
        PoolConfig(
            pool_name="x",
            model="x",
            window_kind="rpm",
            window_duration_seconds=60,
            tokens_allowed=0,
        )


def test_load_pools_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "pools.yaml"
    cfg_path.write_text(
        """
pools:
  - pool_name: gemini-flash
    model: gemini/gemini-2.0-flash-exp
    window_kind: rpm
    window_duration_seconds: 60
    tokens_allowed: 1000000
    quality_weight: 0.7
  - pool_name: glm-4-flash
    model: openai/glm-4-flash
    window_kind: rolling_hours
    window_duration_seconds: 18000
    tokens_allowed: 5000000
"""
    )
    pools = load_pools(cfg_path)
    assert len(pools) == 2
    assert pools[0].pool_name == "gemini-flash"
    assert pools[0].quality_weight == 0.7
    assert pools[1].window_kind == "rolling_hours"
    # default quality_weight when omitted
    assert pools[1].quality_weight == 1.0


def test_load_pools_rejects_missing_top_level(tmp_path: Path) -> None:
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text("not_pools: []\n")
    with pytest.raises(ValueError, match="pools"):
        load_pools(cfg_path)
