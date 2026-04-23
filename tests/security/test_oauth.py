"""Tests for OAuth2Provider.

Spec: Simulated OAuth2 token lifecycle — register, exchange, refresh, validate, revoke.
AC: register_provider stores config, exchange creates deterministic token,
    refresh creates new token, validate checks existence+expiry,
    get_user_info returns claims, revoke removes token.
Edge cases: unknown provider raises, expired token fails validation,
            revoke unknown token is silent, refresh creates separate entry.
Contracts: exchange_code_for_token returns OAuthToken, validate_token returns bool,
           revoke_token is void.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stronghold.security.oauth import OAuth2Provider


class TestRegisterProvider:
    def test_register_and_exchange(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("google", "https://auth", "https://token", "cid", "scope")
        token = oauth.exchange_code_for_token("google", "code", "http://redirect")
        assert token.access_token == "access_token_google"


class TestExchangeCodeForToken:
    def test_unknown_provider_raises(self) -> None:
        oauth = OAuth2Provider()
        with pytest.raises(ValueError, match="not found"):
            oauth.exchange_code_for_token("ghost", "code", "http://r")

    def test_creates_deterministic_token(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("github", "https://a", "https://t", "c", "s")
        token = oauth.exchange_code_for_token("github", "any-code", "any-uri")
        assert token.access_token == "access_token_github"
        assert token.refresh_token == "refresh_token_github"
        assert token.expires_in == 3600
        assert token.user_id == "user_github"
        assert token.roles == ["user"]


class TestRefreshToken:
    def test_unknown_provider_raises(self) -> None:
        oauth = OAuth2Provider()
        with pytest.raises(ValueError, match="not found"):
            oauth.refresh_token("ghost", "rt")

    def test_creates_new_token(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        original = oauth.exchange_code_for_token("p", "code", "uri")
        refreshed = oauth.refresh_token("p", original.refresh_token)
        assert refreshed.access_token == "access_token_p_refreshed"
        assert refreshed.refresh_token == "refresh_token_p_new"

    def test_original_still_valid_after_refresh(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        original = oauth.exchange_code_for_token("p", "code", "uri")
        oauth.refresh_token("p", original.refresh_token)
        assert oauth.validate_token(original.access_token) is True


class TestValidateToken:
    def test_valid_token(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        token = oauth.exchange_code_for_token("p", "code", "uri")
        assert oauth.validate_token(token.access_token) is True

    def test_unknown_token(self) -> None:
        oauth = OAuth2Provider()
        assert oauth.validate_token("nope") is False

    def test_expired_token(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        token = oauth.exchange_code_for_token("p", "code", "uri")
        expired_token = token.access_token
        oauth._tokens[expired_token].created_at = datetime.now(UTC) - timedelta(seconds=7200)
        assert oauth.validate_token(expired_token) is False


class TestGetUserInfo:
    def test_valid_token(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        token = oauth.exchange_code_for_token("p", "code", "uri")
        info = oauth.get_user_info(token.access_token)
        assert info["user_id"] == "user_p"
        assert info["roles"] == ["user"]

    def test_unknown_token_raises(self) -> None:
        oauth = OAuth2Provider()
        with pytest.raises(ValueError, match="Invalid"):
            oauth.get_user_info("nope")


class TestRevokeToken:
    def test_revoke_existing(self) -> None:
        oauth = OAuth2Provider()
        oauth.register_provider("p", "a", "t", "c", "s")
        token = oauth.exchange_code_for_token("p", "code", "uri")
        oauth.revoke_token(token.access_token)
        assert oauth.validate_token(token.access_token) is False

    def test_revoke_nonexistent_silent(self) -> None:
        oauth = OAuth2Provider()
        oauth.revoke_token("nope")
