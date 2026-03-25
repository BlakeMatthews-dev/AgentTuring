"""Config loader: YAML → validated Pydantic StrongholdConfig."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import yaml

from stronghold.types.config import StrongholdConfig

logger = logging.getLogger(__name__)


def _validate_url_not_private(url: str, field_name: str) -> None:
    """Validate that a URL uses HTTPS and does not resolve to private/loopback IPs.

    Args:
        url: The URL to validate.
        field_name: Name of the config field (for error messages).

    Raises:
        ValueError: If the URL fails validation.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        msg = f"{field_name} must use HTTPS scheme, got {parsed.scheme!r}: {url}"
        raise ValueError(msg)

    hostname = parsed.hostname
    if not hostname:
        msg = f"{field_name} has no hostname: {url}"
        raise ValueError(msg)

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # DNS may not resolve at config-load time (e.g. container startup
        # before external DNS is reachable).  Log a warning; the scheme
        # check above is the hard gate.
        logger.warning(
            "%s hostname %r could not be resolved — "
            "skipping private-IP check (will be enforced at connect time)",
            field_name,
            hostname,
        )
        return

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            msg = f"{field_name} resolves to private/loopback/link-local address {ip_str}: {url}"
            raise ValueError(msg)


def load_config(path: str | Path | None = None) -> StrongholdConfig:
    """Load config from YAML file with environment variable overrides."""
    config_path = path or os.getenv("STRONGHOLD_CONFIG", "config/example.yaml")
    config_path = Path(str(config_path))

    if config_path.exists():
        try:
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            msg = f"Invalid YAML in {config_path}: {e}"
            raise ValueError(msg) from e
    else:
        raw = {}

    # Environment variable overrides
    env_overrides: dict[str, str | None] = {
        "database_url": os.getenv("DATABASE_URL"),
        "litellm_url": os.getenv("LITELLM_URL"),
        "litellm_key": os.getenv("LITELLM_MASTER_KEY"),
        "router_api_key": os.getenv("ROUTER_API_KEY"),
        "phoenix_endpoint": os.getenv("PHOENIX_COLLECTOR_ENDPOINT"),
        "webhook_secret": os.getenv("STRONGHOLD_WEBHOOK_SECRET"),
    }
    for key, val in env_overrides.items():
        if val is not None:
            raw[key] = val

    # Validate secret minimum lengths
    router_key = env_overrides.get("router_api_key")
    if router_key and len(router_key) < 32:
        logger.warning(
            "ROUTER_API_KEY is shorter than 32 characters (%d) — "
            "this is insecure and may be rejected in a future version",
            len(router_key),
        )

    webhook_secret = env_overrides.get("webhook_secret")
    if webhook_secret and len(webhook_secret) < 16:
        msg = f"STRONGHOLD_WEBHOOK_SECRET must be at least 16 characters, got {len(webhook_secret)}"
        raise ValueError(msg)

    # Nested config overrides
    cors_origins = os.getenv("STRONGHOLD_CORS_ORIGINS")
    if cors_origins:
        origins = [o.strip() for o in cors_origins.split(",")]
        # CORS validation: reject wildcard "*" and javascript: URIs
        for origin in origins:
            if origin == "*":
                msg = "CORS_ORIGINS must not contain '*' — use exact origins"
                raise ValueError(msg)
            if origin.startswith("javascript:") or origin.startswith("data:"):
                msg = f"CORS_ORIGINS contains unsafe origin: {origin!r}"
                raise ValueError(msg)
            is_local = origin.startswith("http://localhost")
            if origin and not origin.startswith("https://") and not is_local:
                logger.warning(
                    "CORS origin %r is not HTTPS — use HTTPS in production",
                    origin,
                )
        raw.setdefault("cors", {})["allowed_origins"] = origins

    rate_limit_rpm = os.getenv("STRONGHOLD_RATE_LIMIT_RPM")
    if rate_limit_rpm:
        raw.setdefault("rate_limit", {})["requests_per_minute"] = int(rate_limit_rpm)

    max_body = os.getenv("STRONGHOLD_MAX_REQUEST_BODY_BYTES")
    if max_body:
        raw["max_request_body_bytes"] = int(max_body)

    jwks_url = os.getenv("STRONGHOLD_JWKS_URL")
    if jwks_url:
        _validate_url_not_private(jwks_url, "STRONGHOLD_JWKS_URL")
        raw.setdefault("auth", {})["jwks_url"] = jwks_url

    auth_issuer = os.getenv("STRONGHOLD_AUTH_ISSUER")
    if auth_issuer:
        _validate_url_not_private(auth_issuer, "STRONGHOLD_AUTH_ISSUER")
        raw.setdefault("auth", {})["issuer"] = auth_issuer

    auth_audience = os.getenv("STRONGHOLD_AUTH_AUDIENCE")
    if auth_audience:
        raw.setdefault("auth", {})["audience"] = auth_audience

    auth_client_id = os.getenv("STRONGHOLD_AUTH_CLIENT_ID")
    if auth_client_id:
        raw.setdefault("auth", {})["client_id"] = auth_client_id

    auth_authorization_url = os.getenv("STRONGHOLD_AUTH_AUTHORIZATION_URL")
    if auth_authorization_url:
        _validate_url_not_private(auth_authorization_url, "STRONGHOLD_AUTH_AUTHORIZATION_URL")
        raw.setdefault("auth", {})["authorization_url"] = auth_authorization_url

    auth_token_url = os.getenv("STRONGHOLD_AUTH_TOKEN_URL")
    if auth_token_url:
        _validate_url_not_private(auth_token_url, "STRONGHOLD_AUTH_TOKEN_URL")
        raw.setdefault("auth", {})["token_url"] = auth_token_url

    auth_client_secret = os.getenv("STRONGHOLD_AUTH_CLIENT_SECRET")
    if auth_client_secret:
        raw.setdefault("auth", {})["client_secret"] = auth_client_secret

    return StrongholdConfig(**raw)
