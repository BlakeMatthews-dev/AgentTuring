"""Tests for config loader: YAML parsing, env overrides, error handling."""

from __future__ import annotations

import pytest

from stronghold.config.loader import load_config


class TestLoadConfig:
    def test_load_from_nonexistent_path_returns_defaults(self) -> None:
        """When path doesn't exist, returns default config with sensible values."""
        config = load_config("/nonexistent/config.yaml")
        assert config is not None
        assert config.routing.quality_weight == 0.6

    def test_invalid_yaml_raises_value_error(self, tmp_path: object) -> None:
        """Invalid YAML raises ValueError with helpful message."""
        import pathlib

        bad_yaml = pathlib.Path(str(tmp_path)) / "bad.yaml"
        bad_yaml.write_text("{ invalid: yaml: [")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(bad_yaml)

    def test_cors_origins_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_CORS_ORIGINS env var sets CORS allowed_origins."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "http://localhost,http://example.com")
        config = load_config("/nonexistent/path.yaml")
        assert "http://localhost" in config.cors.allowed_origins
        assert "http://example.com" in config.cors.allowed_origins

    def test_rate_limit_rpm_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_RATE_LIMIT_RPM env var sets rate limit."""
        monkeypatch.setenv("STRONGHOLD_RATE_LIMIT_RPM", "120")
        config = load_config("/nonexistent/path.yaml")
        assert config.rate_limit.requests_per_minute == 120

    def test_max_body_bytes_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_MAX_REQUEST_BODY_BYTES env var sets body size limit."""
        monkeypatch.setenv("STRONGHOLD_MAX_REQUEST_BODY_BYTES", "2097152")
        config = load_config("/nonexistent/path.yaml")
        assert config.max_request_body_bytes == 2097152

    def test_jwks_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_JWKS_URL env var sets auth JWKS URL."""
        monkeypatch.setenv("STRONGHOLD_JWKS_URL", "https://sso.example.com/.well-known/jwks.json")
        config = load_config("/nonexistent/path.yaml")
        assert config.auth.jwks_url == "https://sso.example.com/.well-known/jwks.json"

    def test_valid_yaml_loaded(self, tmp_path: object) -> None:
        """Valid YAML file is parsed and values are applied."""
        import pathlib

        good_yaml = pathlib.Path(str(tmp_path)) / "good.yaml"
        good_yaml.write_text("router_api_key: sk-test-from-yaml\n")
        config = load_config(good_yaml)
        assert config.router_api_key == "sk-test-from-yaml"
