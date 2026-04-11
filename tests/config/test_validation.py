"""Tests for configuration validation."""

import pytest
from pydantic import ValidationError

from stronghold.types.config import RoutingConfig, StrongholdConfig, TaskTypeConfig


class TestConfigValidation:
    def test_default_config_is_valid(self) -> None:
        config = StrongholdConfig()
        assert config.routing.quality_weight == 0.6
        assert config.routing.cost_weight == 0.4

    def test_custom_routing_config(self) -> None:
        config = StrongholdConfig(routing=RoutingConfig(quality_weight=0.8, cost_weight=0.2))
        assert config.routing.quality_weight == 0.8

    def test_task_types_parsed(self) -> None:
        config = StrongholdConfig(
            task_types={"code": TaskTypeConfig(keywords=["code"], min_tier="medium")},
        )
        assert "code" in config.task_types
        assert config.task_types["code"].min_tier == "medium"

    def test_empty_providers(self) -> None:
        config = StrongholdConfig(providers={})
        assert len(config.providers) == 0

    def test_permissions_parsed(self) -> None:
        config = StrongholdConfig(permissions={"admin": ["*"], "viewer": ["search"]})
        assert config.permissions["admin"] == ["*"]


class TestRoutingConfig:
    def test_defaults(self) -> None:
        rc = RoutingConfig()
        assert rc.reserve_pct == 0.05
        assert "P2" in rc.priority_multipliers

    def test_custom_multipliers(self) -> None:
        rc = RoutingConfig(priority_multipliers={"P4": 0.5, "P0": 2.0})
        assert rc.priority_multipliers["P4"] == 0.5
