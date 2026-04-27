from __future__ import annotations

import pytest

from turing.self_conduit_mode import (
    ConfigError,
    StartupError,
    resolve_conduit_mode,
    verify_self_ready,
)


class TestResolveConduitMode:
    def test_default_returns_stateless(self):
        assert resolve_conduit_mode() == "stateless"

    def test_yaml_mode_self_returns_self(self):
        assert resolve_conduit_mode(yaml_mode="self") == "self"

    def test_env_overrides_yaml(self, monkeypatch):
        monkeypatch.setenv("TURING_CONDUIT_MODE", "self")
        assert resolve_conduit_mode(yaml_mode="stateless") == "self"

    def test_invalid_mode_raises_config_error(self, monkeypatch):
        monkeypatch.setenv("TURING_CONDUIT_MODE", "invalid")
        with pytest.raises(ConfigError, match="invalid conduit_mode"):
            resolve_conduit_mode()


class TestVerifySelfReady:
    def test_bootstrapped_returns_self_id(self, repo, srepo, bootstrapped_id):
        result = verify_self_ready(repo, srepo)
        assert result == bootstrapped_id

    def test_no_self_raises_startup_error(self, repo, srepo):
        with pytest.raises(StartupError, match="no bootstrapped self"):
            verify_self_ready(repo, srepo)
