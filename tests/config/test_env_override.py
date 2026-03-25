"""Tests for environment variable overrides."""

import os

from stronghold.config.loader import load_config


class TestEnvOverride:
    def test_database_url_from_env(self) -> None:
        os.environ["DATABASE_URL"] = "postgresql://test:test@testhost:5432/testdb"
        try:
            config = load_config()
            assert config.database_url == "postgresql://test:test@testhost:5432/testdb"
        finally:
            del os.environ["DATABASE_URL"]

    def test_litellm_url_from_env(self) -> None:
        os.environ["LITELLM_URL"] = "http://custom-litellm:9999"
        try:
            config = load_config()
            assert config.litellm_url == "http://custom-litellm:9999"
        finally:
            del os.environ["LITELLM_URL"]

    def test_missing_config_file_uses_defaults(self) -> None:
        config = load_config("/nonexistent/path.yaml")
        assert config.routing.quality_weight == 0.6
