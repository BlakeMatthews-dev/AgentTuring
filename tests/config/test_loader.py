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

    def test_valid_yaml_loaded(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid YAML file is parsed and values are applied."""
        import pathlib

        # Ensure env var override does not shadow yaml-provided value
        monkeypatch.delenv("ROUTER_API_KEY", raising=False)
        good_yaml = pathlib.Path(str(tmp_path)) / "good.yaml"
        good_yaml.write_text("router_api_key: sk-test-from-yaml\n")
        config = load_config(good_yaml)
        assert config.router_api_key == "sk-test-from-yaml"


class TestAuthEnvOverrides:
    """STRONGHOLD_AUTH_* env overrides for auth settings in config/loader.py."""

    def test_auth_issuer_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_ISSUER env var sets auth.issuer."""
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_ISSUER", "https://sso.example.com/realms/stronghold"
        )
        config = load_config("/nonexistent/path.yaml")
        assert config.auth.issuer == "https://sso.example.com/realms/stronghold"

    def test_auth_audience_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_AUDIENCE env var sets auth.audience."""
        monkeypatch.setenv("STRONGHOLD_AUTH_AUDIENCE", "stronghold-api")
        config = load_config("/nonexistent/path.yaml")
        assert config.auth.audience == "stronghold-api"

    def test_auth_client_id_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_CLIENT_ID env var sets auth.client_id."""
        monkeypatch.setenv("STRONGHOLD_AUTH_CLIENT_ID", "my-client-id")
        config = load_config("/nonexistent/path.yaml")
        assert config.auth.client_id == "my-client-id"

    def test_auth_authorization_url_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STRONGHOLD_AUTH_AUTHORIZATION_URL env var sets auth.authorization_url."""
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_AUTHORIZATION_URL",
            "https://sso.example.com/realms/stronghold/protocol/openid-connect/auth",
        )
        config = load_config("/nonexistent/path.yaml")
        assert (
            config.auth.authorization_url
            == "https://sso.example.com/realms/stronghold/protocol/openid-connect/auth"
        )

    def test_auth_token_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_TOKEN_URL env var sets auth.token_url."""
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_TOKEN_URL",
            "https://sso.example.com/realms/stronghold/protocol/openid-connect/token",
        )
        config = load_config("/nonexistent/path.yaml")
        assert (
            config.auth.token_url
            == "https://sso.example.com/realms/stronghold/protocol/openid-connect/token"
        )

    def test_auth_client_secret_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STRONGHOLD_AUTH_CLIENT_SECRET env var sets auth.client_secret."""
        monkeypatch.setenv("STRONGHOLD_AUTH_CLIENT_SECRET", "s3cret-value-here")
        config = load_config("/nonexistent/path.yaml")
        assert config.auth.client_secret == "s3cret-value-here"

    def test_database_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL env var sets database_url."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db:5432/stronghold")
        config = load_config("/nonexistent/path.yaml")
        assert config.database_url == "postgresql://user:pass@db:5432/stronghold"

    def test_litellm_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LITELLM_URL env var sets litellm_url."""
        monkeypatch.setenv("LITELLM_URL", "http://litellm:9000")
        config = load_config("/nonexistent/path.yaml")
        assert config.litellm_url == "http://litellm:9000"

    def test_litellm_key_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LITELLM_MASTER_KEY env var sets litellm_key."""
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-litellm-master")
        config = load_config("/nonexistent/path.yaml")
        assert config.litellm_key == "sk-litellm-master"

    def test_router_api_key_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ROUTER_API_KEY env var sets router_api_key."""
        monkeypatch.setenv("ROUTER_API_KEY", "sk-router-abcdefghijklmnopqrstuvwx1234")
        config = load_config("/nonexistent/path.yaml")
        assert config.router_api_key == "sk-router-abcdefghijklmnopqrstuvwx1234"

    def test_phoenix_endpoint_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PHOENIX_COLLECTOR_ENDPOINT env var sets phoenix_endpoint."""
        monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006")
        config = load_config("/nonexistent/path.yaml")
        assert config.phoenix_endpoint == "http://phoenix:6006"

    def test_webhook_secret_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STRONGHOLD_WEBHOOK_SECRET env var sets webhook_secret."""
        monkeypatch.setenv("STRONGHOLD_WEBHOOK_SECRET", "whsec_abcdefghijklmnop")
        config = load_config("/nonexistent/path.yaml")
        assert config.webhook_secret == "whsec_abcdefghijklmnop"


class TestSecretValidation:
    """Secret minimum length enforcement in config/loader.py."""

    def test_short_router_api_key_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ROUTER_API_KEY shorter than 32 chars logs a warning."""
        import logging

        monkeypatch.setenv("ROUTER_API_KEY", "short-key")
        with caplog.at_level(logging.WARNING):
            load_config("/nonexistent/path.yaml")
        assert any("shorter than 32" in r.message for r in caplog.records)

    def test_short_webhook_secret_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STRONGHOLD_WEBHOOK_SECRET shorter than 16 chars raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_WEBHOOK_SECRET", "tooshort")
        with pytest.raises(ValueError, match="at least 16 characters"):
            load_config("/nonexistent/path.yaml")


class TestCorsValidation:
    """CORS origin validation edge cases in config/loader.py."""

    def test_cors_wildcard_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CORS_ORIGINS containing '*' raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "*")
        with pytest.raises(ValueError, match="must not contain"):
            load_config("/nonexistent/path.yaml")

    def test_cors_javascript_uri_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CORS_ORIGINS containing javascript: URI raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "javascript:alert(1)")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_config("/nonexistent/path.yaml")

    def test_cors_data_uri_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CORS_ORIGINS containing data: URI raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "data:text/html,<h1>hi</h1>")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_config("/nonexistent/path.yaml")

    def test_cors_non_https_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-HTTPS, non-localhost CORS origin logs a warning."""
        import logging

        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "http://example.com")
        with caplog.at_level(logging.WARNING):
            load_config("/nonexistent/path.yaml")
        assert any("not HTTPS" in r.message for r in caplog.records)


class TestJwksUrlValidation:
    """JWKS URL SSRF validation in config/loader.py."""

    def test_jwks_url_http_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWKS URL without HTTPS scheme raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_JWKS_URL", "http://sso.example.com/jwks")
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/nonexistent/path.yaml")

    def test_auth_issuer_http_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auth issuer without HTTPS raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_AUTH_ISSUER", "http://sso.example.com/realms/x")
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/nonexistent/path.yaml")

    def test_auth_authorization_url_http_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auth authorization URL without HTTPS raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_AUTH_AUTHORIZATION_URL", "http://sso.example.com/auth")
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/nonexistent/path.yaml")

    def test_auth_token_url_http_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auth token URL without HTTPS raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_AUTH_TOKEN_URL", "http://sso.example.com/token")
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/nonexistent/path.yaml")


class TestValidateUrlNotPrivate:
    """Tests for _validate_url_not_private helper."""

    def test_http_scheme_rejected(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_url_not_private("http://example.com/path", "test_field")

    def test_missing_hostname_rejected(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError, match="no hostname"):
            _validate_url_not_private("https:///path", "test_field")

    def test_private_ip_rejected(self) -> None:
        from stronghold.config.loader import _validate_url_not_private

        with pytest.raises(ValueError, match="private"):
            _validate_url_not_private("https://localhost/path", "test_field")

    def test_unresolvable_hostname_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from stronghold.config.loader import _validate_url_not_private

        with caplog.at_level(logging.WARNING):
            # This hostname should not resolve
            _validate_url_not_private(
                "https://this-hostname-definitely-does-not-exist-xyzzy.example/path",
                "test_field",
            )
        assert any("could not be resolved" in r.message for r in caplog.records)
